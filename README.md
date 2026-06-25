# Productivity Hub Bot (Production Grade)

Your all-in-one Telegram productivity toolkit designed to handle media downloads, document conversions, image processing, QR code scanning/generation, file compression, and advanced text utilities.

The bot features a robust 2-concurrency queue processor, separate rotating logs, automated database backups, automatic security warnings/bans, and a comprehensive Admin console.

---

## Folder Structure

```text
TaskForge/
├── bot.py                     # Root ASGI Webhook & Polling launcher
├── health_check.py            # Standalone diagnostics utility
├── setup_checklist.md         # Checklist for configuration & launch
├── runtime.txt                # Render Python runtime environment setup
├── config/
│   └── settings.py            # Environment configurations & thresholds
├── database/
│   └── bot.db                 # SQLite database file (Persistent)
├── backups/                   # System backups (Daily ZIPs)
├── handlers/
│   ├── start.py               # Start welcoming handlers
│   ├── help.py                # Instructions guides
│   ├── download.py            # Media downloader handler
│   ├── converter.py           # File conversions router
│   ├── image_tools.py         # Pillow image processing actions
│   ├── qr_tools.py            # Generating and scanning QRs
│   ├── compressor.py          # PDF/Image compressions
│   └── admin.py               # Admin operations console (Dashboard)
├── services/
│   ├── download_service.py    # yt-dlp downloader worker
│   ├── conversion_service.py  # Conversions orchestrator
│   ├── image_service.py       # PIL processing actions
│   ├── qr_service.py          # QR scanning & card parsing
│   ├── compression_service.py # PDF & image resizing compression
│   ├── text_service.py        # Casing transformations
│   ├── database_service.py    # SQLite3 persistence manager (pure sqlite3)
│   ├── security_service.py    # Spam, rate limit, auto-bans
│   ├── startup_service.py     # Startup validations & banners
│   └── queue_service.py       # Concurrency queue scheduler
├── utils/
│   ├── validators.py          # URL & size validators
│   ├── helpers.py             # Size formatting & sweep cleaner
│   ├── logger.py              # Rotating log split utility
│   ├── file_detector.py       # MIME categories lookup
│   └── conversion_registry.py # Dynamic conversion matrix
├── temp/
│   ├── downloads/             # Temp downloads
│   ├── uploads/               # Temp uploads
│   ├── converted/             # Temp conversions
│   └── thumbnails/            # Temp media thumbnails
├── logs/                      # Separated rotating log files
├── requirements.txt           # Python dependencies
├── render.yaml                # Render service blueprint definition
├── .env.example               # Environment variables template
└── README.md                  # Main documentation
```

---

## Features

1. **📥 Media Downloader**: Extracts and downloads supported media (video/audio) from YouTube, TikTok, Instagram, Twitter/X, and more.
2. **📄 File Converter**: Dynamically generates conversion targets from the registry (e.g. DOCX -> PDF, TXT, HTML, EPUB, RTF).
3. **🖼 Image Tools**: Support cropping, resizing, rotating, metadata stripping, and thumbnail generation.
4. **🔳 QR Generator & Scanner**: Instantly generate QR codes for text, WiFi configs, and contacts, or upload photos to scan.
5. **📦 File Compressor**: Highly optimized image and PDF size reduction.
6. **📝 Text Utilities**: UPPERCASE, lowercase, Title Case, Sentence Case, duplicate line removal, pretty JSON, and text stats.
7. **⚡ Queue Scheduler**: Restricts active heavy jobs to a maximum of 2 globally, keeping users updated with queue position and estimated wait times.
8. **🔒 Hardened Security**: Automates warnings (attempts $\ge 3$) and permanent bans (attempts $\ge 5$) for unauthorized admin access, spammed rate limits, or queue abuse.

---

## Environment Variables Explanation

Create a `.env` file in the root directory and configure the following variables:

| Variable | Type | Mandatory / Optional | Default Value | Description |
| :--- | :--- | :--- | :--- | :--- |
| `BOT_TOKEN` | String | **Mandatory** | None | The HTTP API token obtained from Telegram's [@BotFather](https://t.me/BotFather). |
| `OWNER_ID` | Integer | **Mandatory** | None | Numeric Telegram User ID of the primary administrator (to access the `/admin` panel). |
| `SECRET_KEY` | String | **Mandatory** | None | Secure cryptographic key. Refuses startup if missing or set to `productivity_hub_default_secret`. |
| `CHANNEL_USERNAME` | String | Optional | None | Telegram channel username (e.g., `@mychannel`) for optional subscription checks. |
| `BOT_MODE` | String | **Mandatory** | `polling` | Operational mode: `polling` for local development, `webhook` for production environments. |
| `WEBHOOK_URL` | String | Conditional | None | Required only when `BOT_MODE=webhook`. Public HTTPS URL where the webserver is reachable. |
| `PORT` | Integer | Optional | `8000` | Port for the FastAPI webhook server to bind to. |
| `DATABASE_PATH` | String | Optional | `database/bot.db` | Relative SQLite database filename location. |
| `DATABASE_URL` | String | Optional | `sqlite:///database/bot.db` | SQLAlchemy-style connection URL to the SQLite database. |
| `LOG_LEVEL` | String | Optional | `INFO` | Console & file logger severity level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). |

---

## Installation & Local Setup

1. **Clone the Repository**:
   ```bash
   git clone <repository_url>
   cd TaskForge
   ```

2. **Configure Virtual Environment**:
   ```bash
   python -m venv venv
   # Activate on Windows:
   .\venv\Scripts\activate
   # Activate on macOS/Linux:
   source venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Setup Environment**:
   - Copy `.env.example` to `.env`:
     ```bash
     cp .env.example .env
     ```
   - Open `.env` and fill in `BOT_TOKEN`, `OWNER_ID`, and a secure `SECRET_KEY`.

5. **Initialize Database**:
   ```bash
   python -c "from services.database_service import init_db; init_db()"
   ```

6. **Run Health Diagnostics**:
   Ensure everything is configured correctly:
   ```bash
   python health_check.py
   ```

7. **Start the Bot**:
   ```bash
   python bot.py
   ```

---

## Production Deployment Guide

### Render Setup
1. Log in to Render and create a new **Web Service** mapped to your repository.
2. Render will automatically detect `render.yaml`. Confirm settings and click deploy.
3. Configure a persistent Disk mount to keep database records:
   - **Name**: `db-volume`
   - **Mount Path**: `/app/database`
   - **Size**: 1 GB
4. In your Web Service settings on Render, navigate to **Environment** and configure the required environment variables:
   - `BOT_TOKEN`, `OWNER_ID`, `SECRET_KEY`, `WEBHOOK_URL` (your web service domain on Render, e.g., `https://your-service.onrender.com`), and `BOT_MODE=webhook`.
5. Ensure the health check path is configured to `/health`.

### Railway Setup
1. Log in to Railway and create a new project. Select **Deploy from GitHub**.
2. Go to the service settings and click **Add Volume** to mount a persistent volume at `/app/database`.
3. In the variables tab, add all variables from the `.env.example` file.
4. Railway will automatically build and run the bot from the start command:
   `uvicorn bot:app --host 0.0.0.0 --port $PORT` using the Python runtime.

### Replit Setup
1. Import the repository directly into Replit.
2. In the Replit side panel, go to **Tools -> Secrets** and enter all environment variables (`BOT_TOKEN`, `OWNER_ID`, etc.).
3. The Replit workspace directory persists by default. Setup the start command to:
   `python bot.py` and run.

---

## Troubleshooting

1. **Ffmpeg missing error**: Media downloader and compressor tools require `ffmpeg` installed on the host system.
   - For Local Setup: Download FFmpeg and add it to your system PATH.
   - For Render/Railway: Built-in builders include FFmpeg automatically.
2. **Permission errors on SQLite database**: Ensure the directory `/app/database` has read/write permissions.
3. **Webhook errors**: In Webhook mode, verify `WEBHOOK_URL` is an HTTPS url, and matches your public endpoint domain.
