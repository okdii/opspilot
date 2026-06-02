FROM python:3.11-slim

# Non-root user for security
RUN groupadd -r opspilot && useradd -r -g opspilot opspilot

WORKDIR /app

# Dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure migrations dir is accessible
RUN chown -R opspilot:opspilot /app

USER opspilot

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
