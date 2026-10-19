"""
Root Entrypoint & Backward-Compatible Deployment Runner.

Supports both direct process execution (Render startCommand: python bot.py or python productivity_hub/bot.py)
and ASGI web container execution (gunicorn bot:app -k uvicorn.workers.UvicornWorker).
Preserves existing deployment environments without breaking legacy CI/CD commands.
"""

import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Provide ASGI app instance for Gunicorn / Uvicorn compatibility
try:
    from fastapi import FastAPI, Response
    app = FastAPI(title="Productivity Hub Bot Webhook & Health Service")

    @app.get("/health")
    @app.get("/")
    async def health_check():
        return {"status": "ok", "service": "productivity-hub"}

except ImportError:
    app = None


def main():
    """Delegate execution to productivity_hub.bot.main()."""
    from productivity_hub.bot import main as hub_main
    hub_main()


if __name__ == "__main__":
    main()
