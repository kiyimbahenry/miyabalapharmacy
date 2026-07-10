# Python example - adjust if you're using another language
FROM python:3.9-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Run gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]
