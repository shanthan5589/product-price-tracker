FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Keep apt lists so playwright --with-deps can install Chromium system libraries
RUN apt-get update && apt-get install -y --no-install-recommends gcc

COPY price_tracker/requirements.txt .

# Install CPU-only torch first (~200 MB) so the requirements.txt pass sees it
# already satisfied and skips the 2.5 GB CUDA wheel from PyPI
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Chromium + system libraries; needs the apt lists preserved above
RUN playwright install --with-deps chromium

COPY price_tracker/ ./

RUN SECRET_KEY=build-only python manage.py collectstatic --no-input

COPY start.sh /start.sh
RUN chmod +x /start.sh

EXPOSE 8000
CMD ["/start.sh"]
