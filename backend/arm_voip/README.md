# arm_voip: телефония тренажёра

Сервис имитирует входящий звонок обучающемуся. Asterisk звонит на SIP-номер
оператора, после ответа играет запись сценария (голос заявителя), сервис
замеряет задержку и сообщает `arm_api` о ходе звонка.

```
браузер (софтфон) <--WebRTC/SIP--> Asterisk <--ARI (HTTP + WebSocket)--> arm_voip <--HTTP--> arm_api
```

## Как проходит звонок

1. Обучающийся запрашивает карточку: `POST /sessions/{id}/attempts/next`.
2. `arm_api` создаёт карточку и вызов, фиксирует их в БД и только после этого
   вызывает `arm_voip` (`POST /calls`). Иначе быстрые события (например,
   «не дозвонились») пришли бы раньше, чем появилась строка `calls`.
3. `arm_voip` берёт свободный номер из пула (по одному на карточку), просит
   Asterisk позвонить на него и возвращает реквизиты софтфона (`call.sip` в
   ответе `next`: номер, пароль, `ws_url`, домен).
4. Софтфон в браузере регистрируется этим номером, ему приходит звонок.
5. Обучающийся отвечает: Asterisk отдаёт канал приложению Stasis `arm_voip`,
   сервис включает запись из `scenario.legend.audio` и присылает `answered`.
6. Пока идёт разговор, раз в `VOIP_RTT_POLL_SEC` секунд снимается RTT по RTCP.
7. Звонок завершается по `submit`/`finish` (`DELETE /calls/{id}`) или когда
   трубку положили. Номер возвращается в пул, в `arm_api` уходит `finished` с
   RTT и признаком `latency_ok`.

Если VoIP недоступен, занятие продолжается текстовым диалогом
(`call.degraded = true`).

## Задержка (ТЗ: не более 150 мс)

Односторонняя задержка оценивается как половина RTT по RTCP. Если максимальный
RTT за звонок превышает `2 x VOIP_MAX_LATENCY_MS`, `arm_api` пишет событие в
системный журнал и открывает оповещение `voip.latency` (раздел «Состояние
системы»). RTT сохраняется в `calls.rtt_ms`. RTCP-статистика появляется через
несколько секунд после начала разговора, до этого замера нет.

## Настройка

```bash
cp arm_voip/.env_example arm_voip/.env     # заполнить CHANGE_ME
```

| Переменная | Назначение |
|---|---|
| `ARI_PASSWORD` | пароль ARI, подставляется в `ari.conf` при старте Asterisk |
| `ARM_VOIP_SERVICE_TOKEN` | общий токен с `arm_api` (там же переменная `ARM_VOIP_SERVICE_TOKEN`) |
| `VOIP_SIP_SECRET` | секрет, из которого выводятся пароли SIP-номеров |
| `VOIP_POOL_SIZE` | число одновременных звонков (по ТЗ не менее 20) |
| `VOIP_ENDPOINT_MODE` | `webrtc` (браузер) или `sip` (аппаратный IP-телефон по UDP) |
| `SIP_WS_URL`, `SIP_DOMAIN` | что получает браузер для регистрации |
| `VOIP_DESTINATION` | необязательно: всегда звонить на один номер, без пула |

В `arm_api/.env`: `VOIP_ENABLED=1`, `ARM_VOIP_BASE_URL=http://arm_voip:8001`,
тот же `ARM_VOIP_SERVICE_TOKEN`.

Запуск из каталога `backend`: `docker compose up --build`.

### Звуковые записи

Записи кладутся в том `voip_audio` (в `arm_voip` он доступен как `/audio`), в
сценарии указывается имя: `"legend": {"audio": "fire_flat"}` (подойдёт
`fire_flat.wav` или `fire_flat.mp3`). Сервис приводит запись к формату телефонии
(WAV, 8 кГц, моно) через ffmpeg. Если записи нет, звонок идёт без звука.

### HTTPS для микрофона

Браузер разрешает микрофон только на защищённой странице. Для стенда положите
сертификат в Asterisk и раскомментируйте блок `tls*` в `asterisk/http.conf`,
порт 8089, затем `SIP_WS_URL=wss://<хост>:8089/ws`. На `localhost` работает и без
HTTPS.

## Что нужно фронтенду

В ответе `POST /sessions/{id}/attempts/next` поле `call.sip`:

```json
{ "extension": "2001", "password": "...", "ws_url": "ws://host:8088/ws", "domain": "host", "mode": "webrtc" }
```

Пример с JsSIP:

```js
const ua = new JsSIP.UA({
  sockets: [new JsSIP.WebSocketInterface(sip.ws_url)],
  uri: `sip:${sip.extension}@${sip.domain}`,
  password: sip.password,
});
ua.on("newRTCSession", ({ session }) => {
  if (session.direction === "incoming") {
    // показать «Входящий вызов», по кнопке «Принять»:
    session.answer({ mediaConstraints: { audio: true, video: false } });
    // и вызвать POST /attempts/{id}/answer
  }
});
ua.start();
```

Проверка линии без сценария: с софтфона набрать `600` (эхо) или `601`
(тестовая запись).

## Служебные точки

| Точка | Назначение |
|---|---|
| `POST /calls` | создать звонок (токен `X-Service-Token`) |
| `GET /calls/{id}` | состояние звонка |
| `DELETE /calls/{id}` | завершить звонок |
| `GET /health` | доступность ARI, поток событий, занятость пула |
| `POST /api/v1/internal/voip/events` в `arm_api` | приём событий от этого сервиса |

## Ограничения

- Состояние пула и звонков хранится в памяти, поэтому сервис работает в одном
  процессе uvicorn. После перезапуска активные звонки теряются (карточка при
  этом остаётся, звонок закрывается по таймауту).
- Пароль SIP-номера выдаётся только обладателю аренды. Общий секрет должен быть
  известен только `arm_voip` и Asterisk.
- За NAT и при работе Asterisk в Docker без host-сети нужны `external_media_address`
  и `external_signaling_address` в транспорте (`asterisk/pjsip.conf`).
- Автоматической проверки на живом Asterisk в репозитории нет: тесты
  (`pytest`) используют подмену ARI и настоящий WebSocket-сервер.

## Тесты

```bash
cd arm_voip && pip install -e . pytest pytest-asyncio && pytest
```
