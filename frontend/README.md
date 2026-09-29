# Фронтенд АРМ-112

React 19 + TypeScript + Vite. Без UI-библиотек: стили в `src/styles`, палитра снята с макетов (`APM-112_Figma`).

## Запуск для разработки
```
npm install
npm run dev            # http://127.0.0.1:5173, /api проксируется на http://127.0.0.1:5000
```
Другой адрес API: `VITE_API_TARGET=http://host:port npm run dev`.
На macOS порт 5000 занят AirPlay: запускайте бэкенд на другом порту (`flask run -p 5001`) и передайте `VITE_API_TARGET`, либо обращайтесь по `127.0.0.1`.

## Сборка
`npm run build` → `dist/` (nginx из `backend/proxy` раздаёт эту папку).

## Экраны
| Маршрут | Роль | Экраны макета |
|---|---|---|
| `/login` | все | 01, 35 |
| `/arm/:sessionId` | обучающийся | 02-16, 21 (журнал, вызов, карточка, службы, результат) |
| `/student`, `/student/progress`, `errors`, `library`, `profile` | обучающийся | 17-20 |
| `/teacher`, `scenarios`, `generate`, `sessions`, `monitor`, `reports`, `analytics`, `groups` | преподаватель | 22-30 |
| `/admin`, `users`, `settings`, `backups`, `audit`, `reports`, `security` | администратор | 31-34 |

## Структура
`src/api` клиент и типы · `src/auth` вход, refresh, роли · `src/components` каркас, графики, UI · `src/pages` экраны · `src/lib` хуки, формат.

## Не сделано
Браузерный софтфон (JsSIP) для голосового канала: сейчас голос сопровождается текстовым чатом. Уточнения по типам происшествий (макеты 07-09) и карта (12) упрощены до полей карточки.
