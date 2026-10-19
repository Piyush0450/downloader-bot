"""
Health Check HTTP Web Server.

Provides a lightweight, non-blocking aiohttp HTTP web server to respond to Render
cloud platform health probes at GET /health. Strictly avoids exposing any credentials,
internal tokens, or server filesystem paths.
"""

import logging
from typing import Optional
from aiohttp import web

logger = logging.getLogger("productivity_hub.web.health")


class HealthCheckServer:
    """
    Lightweight aiohttp web server handling health check endpoints for cloud monitoring.
    """

    def __init__(self, port: int = 8000, host: str = "0.0.0.0"):
        self.port = port
        self.host = host
        self.app: web.Application = web.Application()
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Register public HTTP routes."""
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/", self.handle_health)

    async def handle_health(self, request: web.Request) -> web.Response:
        """
        GET /health endpoint handler.

        Returns:
            JSON response: {"status": "ok", "service": "productivity-hub"} with HTTP 200.
        """
        return web.json_response(
            {
                "status": "ok",
                "service": "productivity-hub"
            },
            status=200
        )

    async def start(self) -> None:
        """Start the HTTP server asynchronously without blocking the main event loop."""
        logger.info(f"Starting Health Check HTTP server on {self.host}:{self.port}...")
        self.runner = web.AppRunner(self.app, access_log=None)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()
        logger.info(f"Health Check HTTP server active and listening on http://{self.host}:{self.port}/health")

    async def stop(self) -> None:
        """Stop and cleanup HTTP server resources gracefully."""
        if self.site:
            logger.info("Stopping Health Check HTTP server site...")
            await self.site.stop()
            self.site = None
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
        logger.info("Health Check HTTP server stopped gracefully.")


# Global server instance holder
_health_server_instance: Optional[HealthCheckServer] = None


async def start_health_server(port: int = 8000, host: str = "0.0.0.0") -> HealthCheckServer:
    """
    Convenience function to initialize and start the global HealthCheckServer instance.

    Args:
        port: Listening port.
        host: Listening network interface.

    Returns:
        HealthCheckServer: Active server instance.
    """
    global _health_server_instance
    _health_server_instance = HealthCheckServer(port=port, host=host)
    await _health_server_instance.start()
    return _health_server_instance


async def stop_health_server() -> None:
    """Convenience function to stop global HealthCheckServer instance."""
    global _health_server_instance
    if _health_server_instance:
        await _health_server_instance.stop()
        _health_server_instance = None
