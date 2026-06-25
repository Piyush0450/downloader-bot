FROM python:3.10-slim-buster

# Prevent python from writing pyc files to disk and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies (including unrar-free and p7zip-full for archive extractions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    ffmpeg \
    poppler-utils \
    ghostscript \
    p7zip-full \
    unrar-free \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create necessary directories
RUN mkdir -p database temp/downloads temp/uploads temp/converted logs && chmod 777 database temp temp/downloads temp/uploads temp/converted logs

# Expose port (Render sets PORT env)
EXPOSE 8000

# Run FastAPI app with Gunicorn and Uvicorn workers
CMD ["sh", "-c", "gunicorn bot:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-8000}"]
