# Use Python 3.14-slim or fallback to 3.13-slim
FROM python:3.14-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=stockcontrol.settings_cloud

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY stockcontrol/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Django project
COPY stockcontrol/ .

# Create directory for static files (if it doesn't exist)
RUN mkdir -p staticfiles

# Collect static files
RUN python manage.py collectstatic --noinput

# Expose port
EXPOSE 8080

# Run with gunicorn using cloud settings
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "stockcontrol.wsgi:application"]
