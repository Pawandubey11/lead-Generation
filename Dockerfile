FROM python:3.11-slim

WORKDIR /app

# Prevent Python from writing .pyc and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# 1. Install system dependencies required by Playwright & Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2t64 \
    && rm -rf /var/lib/apt/lists/*

# 2. Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Install Chromium browser binaries and dependencies for Playwright
RUN python -m playwright install --with-deps chromium

# 4. Copy the entire application code
COPY . .

# 5. Create directories for data and logs
RUN mkdir -p /app/output /app/logs /app/data

# 6. Default environment variables
ENV PORT=8000
ENV LEADS_CSV_PATH=/app/output/final_ai_leads.csv
ENV LEADPULSE_DEV_MODE=true
ENV LEADPULSE_SECRET_KEY=leadpulse-secure-prod-key-7f9e8a1b3c5d6e7f8a9b0c1d2e3f4a5b

EXPOSE 8000

# 7. Start FastAPI web dashboard using dynamic PORT assigned by cloud host
CMD ["sh", "-c", "uvicorn dashboard.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
