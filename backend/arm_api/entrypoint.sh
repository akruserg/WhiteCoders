#!/bin/sh
set -e

export FLASK_APP="arm_api.app:app"

echo "* entrypoint [arm_api] - применение миграций БД"
flask db upgrade

echo "* entrypoint [arm_api] - начальные данные (справочники, шаблон карточки, настройки)"
if [ "${SEED_DEMO:-0}" = "1" ]; then
    python -m arm_api.services.seed --demo
else
    python -m arm_api.services.seed
fi

echo "* entrypoint [arm_api] - запускаем ежедневный бекап БД и очистку журнала"
python -c "from arm_api.services.backup import run_loop; run_loop()" &

echo "* entrypoint [arm_api] - запускаем gunicorn"
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --workers "${GUNICORN_WORKERS:-4}" \
    --threads "${GUNICORN_THREADS:-8}" \
    --timeout "${GUNICORN_TIMEOUT:-300}" \
    arm_api.app:app
