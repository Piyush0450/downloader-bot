FROM python:3.11-slim

# Prevent python from writing pyc files to disk and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies (FFmpeg, LibreOffice, Poppler, Ghostscript, 7z, UnRAR, ZBar)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    ffmpeg \
    poppler-utils \
    ghostscript \
    p7zip-full \
    unrar-free \
    libzbar0 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create necessary directories
RUN mkdir -p database temp/downloads temp/uploads temp/converted temp/compressed temp/thumbnails logs backups \
    && chmod -R 777 database temp logs backups

# Expose port (Render sets PORT env, default 8000)
EXPOSE 8000

# Run Productivity Hub Bot with integrated aiohttp health check server
CMD ["python", "bot.py"]
