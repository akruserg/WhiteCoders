#!/bin/sh
# Скачивает голоса Piper (TTS, ~63 МБ каждый) и модель faster-whisper (STT).
# Нужен доступ в интернет один раз; после этого контур работает изолированно,
# каталог models можно просто скопировать на закрытый сервер (как с llm/models).
set -eu

DIR="$(cd "$(dirname "$0")" && pwd)/models"
PIPER_DIR="$DIR/piper"
WHISPER_DIR="$DIR/whisper"
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU"

mkdir -p "$PIPER_DIR" "$WHISPER_DIR"

# два голоса заявителя: мужской и женский (реплика в сценарии выбирает любой)
for voice in denis:male irina:female; do
    name="${voice%%:*}"
    file="ru_RU-${name}-medium"
    [ -f "$PIPER_DIR/$file.onnx" ] || curl -fL -C - --progress-bar \
        -o "$PIPER_DIR/$file.onnx" "$BASE/$name/medium/$file.onnx"
    [ -f "$PIPER_DIR/$file.onnx.json" ] || curl -fsSL \
        -o "$PIPER_DIR/$file.onnx.json" "$BASE/$name/medium/$file.onnx.json"
done

# модель распознавания речи (faster-whisper скачивает сам при первом запуске,
# если WHISPER_DIR пуст; здесь только прогреваем кэш заранее, чтобы первый
# настоящий звонок не ждал загрузки ~500 МБ)
python3 - "$WHISPER_DIR" "${STT_MODEL_SIZE:-small}" <<'PY'
import sys
from faster_whisper import WhisperModel

download_root, size = sys.argv[1], sys.argv[2]
WhisperModel(size, device="cpu", compute_type="int8", download_root=download_root)
print(f"Модель распознавания речи '{size}' готова в {download_root}")
PY

echo "Готово: $PIPER_DIR (голоса Piper), $WHISPER_DIR (faster-whisper)"
