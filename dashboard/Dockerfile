FROM python:3.11-slim

WORKDIR /app

# Install system dependencies required by Playwright/Chromium
RUN apt-get update && apt-get install -y \
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

# Install Python dependencies from root requirements.txt only
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium browser for Playwright (used by scraper_service inside dashboard)
RUN python -m playwright install chromium

# Copy all project files
COPY . .

# Ensure output and logs directories exist
RUN mkdir -p /app/output /app/logs

EXPOSE 8000

# Launch FastAPI dashboard via uvicorn
# Running from /app so relative imports (scrapers.crawler, config.config) resolve correctly
CMD ["uvicorn", "dashboard.app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
