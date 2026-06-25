# Deployment Guide: Productivity Hub Bot

This guide provides step-by-step instructions for deploying the **Productivity Hub Bot** locally (Polling mode) and to production on **Render** (Webhook mode with Gunicorn and a Dockerized environment).

---

## Production Deployment on Render

Render web services must bind to a port specified by the `$PORT` environment variable and pass health checks. The bot runs in **Webhook mode** using a FastAPI web backend running under **Gunicorn** with **Uvicorn workers**.

### Step 1: Create a Persistent Disk
Since we use SQLite as the database engine, and Render container filesystems are ephemeral (wiped on redeploys), we must use a **Persistent Disk** to mount the database folder.
1. In the Render Dashboard, you can deploy using the `render.yaml` blueprint or configure a Web Service manually.
2. If manually configuring:
   - Go to the **Disks** section of your Web Service.
   - Click **Add Disk**.
   - Set **Name** to: `db-volume`
   - Set **Mount Path** to: `/app/database`
   - Set **Size** to: `1 GiB` (minimum, plenty for SQLite records).

### Step 2: Configure Environment Variables
Set the following environment variables in the **Environment** tab:
- `BOT_TOKEN`: *Your official Telegram Bot Token (obtained from @BotFather)*
- `OWNER_ID`: *Your personal Telegram User ID (used for owner authorization check)*
- `SECRET_KEY`: *A long, randomly generated secret string*
- `BOT_MODE`: `webhook`
- `WEBHOOK_URL`: `https://your-service-name.onrender.com`

### Step 3: Deployment Setup
1. Create a new **Web Service** on Render.
2. Select your repository.
3. Select **Docker** as the runtime. Render will automatically detect the `Dockerfile` at the root.
4. Deploy the service.

During deployment, Render builds the image from the `Dockerfile` which installs:
- **LibreOffice** (for headless document conversions)
- **FFmpeg** (for audio/video conversions)
- **Poppler Utilities** (for PDF page-to-image extraction)
- **Ghostscript** (for PDF compression tools)
- **7z / Unrar** (for ZIP, RAR, and 7Z archive extractions)

The service starts Uvicorn ASGI workers under Gunicorn:
`gunicorn bot:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT`

---

## Local Setup (Development)

To test the bot locally without webhooks:

1. Clone the repository and navigate to the directory:
   ```bash
   cd TaskForge
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   # On Windows:
   .\venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Create your `.env` file from the template:
   ```bash
   cp .env.example .env
   # Open .env and set your BOT_TOKEN and OWNER_ID
   ```

5. Ensure you have local binaries for `ffmpeg` and `libreoffice` added to your system PATH if you plan to test conversion utilities locally. If missing, the bot will gracefully fall back to pure-Python libraries (e.g. `pypdf`, `pdf2docx`, `openpyxl`).

6. Run the bot in polling mode:
   ```bash
   python bot.py
   ```

7. Run the unit tests to confirm:
   ```bash
   python -m unittest tests/test_bot_v2.py
   ```
