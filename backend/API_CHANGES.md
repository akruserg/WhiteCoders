# Что изменилось в API (для фронтенда)

Полный список маршрутов: `../api.txt` (128). Полная спецификация: `GET /api/v1/openapi.json`.
Ошибки везде: `{"error": {"code", "message", "details"}, "request_id"}`.

## Изменения существующего поведения

| Где | Что изменилось |
|---|---|
| `POST/PATCH /sessions`, `/scenarios`, импорт и генерация сценариев | `time_limit_sec` необязателен и может быть `null`. Приоритет при выдаче карточки: занятие, сценарий, профиль оценивания, 30 с. **Всегда показывайте `attempt.time_limit_sec` из выданной карточки**, а не поле занятия |
| `POST /attempts/{id}/submit`, `GET /attempts/{id}` (обучающийся) | если занятие идёт в режиме аттестации, в ответе только `score`, `passed`, `status`, время и `details_hidden`; полей `errors` и `breakdown` **нет** до завершения занятия |
| `POST /reports` | новый вид `system_errors` (только системные данные, доступен администратору). Отчёт о занятии-аттестации содержит блок `attestation` и заголовок «Протокол аттестации». PDF показывает не более 3000 строк таблицы (пометка внизу), полные данные в csv, xlsx, json |
| `GET /me/progress` | добавлено поле `forecast_accuracy` (точность прогноза для этого обучающегося) |
| `POST /materials` | материал индексируется для ИИ сразу; в ответе `is_indexed` (false для аудио) |
| `POST /materials/{id}/index` | реально разбирает файл; ответ содержит `chunks` |
| `GET /roles` | права ролей могут отличаться от значений по умолчанию (их редактирует администратор) |
| Права | проверяются по БД на каждый запрос: изменение матрицы действует сразу, перелогин не нужен |
| `POST /attempts/{id}/messages` | при включенном ИИ (`AI_ENABLED=1`) реплика заявителя генерируется нейросетью с учетом легенды и истории разговора, а не берется из заготовок сценария; заготовки остаются запасным путем, если ИИ выключен или не ответил. Формат ответа не изменился |

## Новые маршруты

**Аттестация.** В `POST /sessions` можно передать `"attestation": {"pass_score": 75, "min_attempts": 3, "certificate": true, "valid_months": 12}` (все поля необязательны).
`GET /sessions/{id}/attestation` (преподаватель): протокол `{config, students: [{full_name, attempts, average, passed, enough_attempts, certificate}], passed, total}`.
После `POST /sessions/{id}/finish` итог также лежит в `session.settings.attestation_result`, сертификаты выданы автоматически.

**Матрица прав** (администратор): `GET /roles/matrix`, `PUT /roles/{code}/permissions` с телом `{"permissions": [...], "comment": ""}`,
`POST /roles/{code}/permissions/reset`. Нарушение правил: 422, `code = role_rules_violated`, `details.problems`.

**Настройки** `/system/settings`: новые ключи `perf.*` (применяются при перезапуске узла, кроме `perf.max_active_sessions` и `perf.report_warn_sec`) и `notify.*`.
`POST /system/notify/test`: проверка доставки оповещений, ответ `{configured, channels: {webhook|email: "ok" | текст ошибки}}`.

**Аналитика:** `GET /analytics/forecast-accuracy?user_id=&group_id=&session_id=&category_id=`: `{available, n, mae, rmse, bias, hit_rate, skill, reliability}`
(`reliability`: `insufficient`, `low`, `medium`, `high`).

**Материалы:** `GET /materials/search?q=&category_id=&limit=` (преподаватель): что увидит ИИ при генерации.

**Пакетное обновление** (администратор): `POST /system/updates` (multipart, поле `file`, zip), `?dry_run=1` только проверка; `GET /system/updates` история.

**Рабочие места (АРМ):** `/workstations` (CRUD), `/workstations/{id}/config.xml`, `/workstations/export.xml`, `POST /workstations/import` (XML), `GET /me/workstation`.

**XML вместо JSON:** любой маршрут принимает `Content-Type: application/xml` и отдаёт XML при `Accept: application/xml` или `?format=xml`.

**Голосовой диалог по VoIP** (новое): при `VOICE_DIALOG_ENABLED=1` в `arm_voip` звонок перестает быть
«без звука по умолчанию» - речь оператора распознается (STT, сервис `voice`), передается сюда через
служебный `POST /internal/calls/{sip_call_id}/voice-turn` (ответ - `{"reply": "..."}`), а ответ заявителя
озвучивается (TTS) и играется обратно в звонок. Реплики обеих сторон попадают в ту же стенограмму, что
и текстовый чат (`GET /attempts/{id}/messages`) - фронтенду ничего не нужно менять, чтобы их показать.
Требования к серверу и включение - `backend/voice/README.md`, `backend/arm_voip/.env_example`.

## Новые коды ошибок

| Код | HTTP | Когда |
|---|---|---|
| `capacity_reached` | 409 | достигнут предел одновременных занятий (`perf.max_active_sessions`) при старте занятия |
| `sessions_running` | 409 | пакетное обновление во время идущих занятий |
| `backup_required` | 409 | нужна свежая резервная копия (`POST /system/backups`) |
| `already_applied` | 409 | пакет или версия обновления уже применены |
| `bad_package` | 422 | пакет обновления не прошёл проверку, `details` подробно |
| `role_rules_violated` | 422 | набор прав роли нарушает ограничения |
| `not_attestation` | 409 | протокол запрошен у обычного занятия |
| `db_unavailable` | 503 | БД недоступна (заголовок `Retry-After`) |

## Сбой БД и ответ 202

Если БД временно недоступна, `PUT /attempts/{id}/draft` и `POST /attempts/{id}/submit` не теряют данные:
ответ **202** `{"status": "buffered", "buffer_id", "kind", "attempt_id", "received_at", "message"}`.
Обработка идёт автоматически после восстановления, время ответа считается по моменту получения.
Клиенту нужно показать «ответ принят, результат появится позже» и опросить `GET /attempts/{id}`
(409 «еще не оценена», пока идёт обработка). Все остальные запросы в этот момент получают 503 с `Retry-After`.
Для браузера заголовки `Retry-After` и `X-Request-Id` открыты через CORS.

## Локальный запуск для разработки фронта

В `arm_api/.env` укажите `CORS_ORIGINS=http://localhost:5173` (адрес вашего dev-сервера). Тестовые
данные: `SEED_DEMO=1` создаёт три утверждённых сценария; администратор создаётся из `ADMIN_USERNAME`
и `ADMIN_PASSWORD`. Пользователей других ролей создаёт администратор через `POST /users`.
