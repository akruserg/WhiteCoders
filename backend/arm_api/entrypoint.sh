#!/bin/sh
set -e

export FLASK_APP="arm_api.app:app"

echo "* entrypoint [arm_api] - применение миграций БД"
flask db upgrade

echo "* entrypoint [arm_api] - запускаем ежедневный бекап БД"
python -c "from arm_api.services.backup import run_loop; run_loop()" &

echo "* entrypoint [arm_api] - запускаем gunicorn"
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 4 \
    --threads 2 \
    arm_api.app:app