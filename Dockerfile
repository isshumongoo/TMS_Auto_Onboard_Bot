FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tzdata && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Persistent disk path for DB (Render disk will mount here)
ENV ONBOARDING_DB_PATH=/data/onboarding.db

# Non-root
RUN useradd -m appuser
USER appuser

CMD ["python", "app.py"]
