# ---- Base image
FROM python:3.11-slim

# ---- Basic env
ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ONBOARDING_DB_PATH=/data/onboarding.db

# ---- OS deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

# ---- Workdir
WORKDIR /app

# ---- Install Python deps first (better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- App code
COPY app.py .

# ---- (Optional) Healthcheck - process must be running to pass
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import os,sys; sys.exit(0)"

# ---- Run the bot (Socket Mode)
CMD ["python", "app.py"]
