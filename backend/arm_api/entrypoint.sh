#!/bin/sh
set -e

export FLASK_APP="arm_api.app:app"

# echo "* entrypoint - applying database migrations"
# flask db upgrade

echo "* entrypoint [arm_api] - starting gunicorn"
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 4 \
    --threads 2 \
    arm_api.app:app