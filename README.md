# Miyabala Pharmacy - Cloud Run Deployment

## Dockerfile Overview

This project uses a Dockerfile to containerize the application for deployment on Google Cloud Run.

### Dockerfile Configuration

The Dockerfile uses a multi-stage build process:

```dockerfile
# Use Python 3.9 slim image for smaller footprint
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port 8080 (Cloud Run default)
EXPOSE 8080

# Run with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]
