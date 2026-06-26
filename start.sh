#!/usr/bin/env bash
set -o errexit

python manage.py collectstatic --no-input
exec gunicorn crm1.wsgi:application --bind "0.0.0.0:${PORT:-8000}"
