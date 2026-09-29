#!/bin/sh
# Скачивает модель YandexGPT-5-Lite-8B-instruct (Q4_K_M, около 5 ГБ) в llm/models.
# Нужен доступ в интернет один раз; после этого контур работает изолированно,
# каталог models можно просто скопировать на закрытый сервер.
set -eu

DIR="$(cd "$(dirname "$0")" && pwd)/models"
FILE="YandexGPT-5-Lite-8B-instruct-Q4_K_M.gguf"
BASE="https://huggingface.co/yandex/YandexGPT-5-Lite-8B-instruct-GGUF/resolve/main"

mkdir -p "$DIR"
[ -f "$DIR/LICENSE" ] || curl -fsSL -o "$DIR/LICENSE" "$BASE/LICENSE"
curl -fL -C - --progress-bar -o "$DIR/$FILE" "$BASE/$FILE"   # -C - докачивает при обрыве

echo "Готово: $DIR/$FILE"
echo "Лицензия YandexGPT-5-Lite-8B: коммерческое использование бесплатно до 10 млн"
echo "выходных токенов в месяц, подробности в $DIR/LICENSE"
