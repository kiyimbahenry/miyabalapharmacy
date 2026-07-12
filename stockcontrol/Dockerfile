FROM python:3.14-slim

# Cloud Run specific settings
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=stockcontrol.settings_cloud
ENV CLOUD_RUN=true

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY stockcontrol/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY stockcontrol/ .

# Create static directory
RUN mkdir -p staticfiles

EXPOSE 8080

# Run migrations, collect static, create superuser, and start server
CMD ["sh", "-c", "python3 manage.py migrate --noinput && python3 manage.py collectstatic --noinput && python3 manage.py createsuperuser --noinput --username $DJANGO_SUPERUSER_USERNAME --email $DJANGO_SUPERUSER_EMAIL || true && gunicorn --bind 0.0.0.0:8080 stockcontrol.wsgi:application"]
