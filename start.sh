#!/bin/sh
set -e
python manage.py migrate --no-input
python manage.py shell -c \
  "from tracker.models import Product; import sys; sys.exit(0 if Product.objects.exists() else 1)" \
  || python manage.py loaddata initial_products
exec gunicorn price_tracker.wsgi:application \
  --bind 0.0.0.0:${PORT:-8000} \
  --workers 2
