import logging
from contextvars import ContextVar

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# ContextVar accessible from MCP tools to identify the current user
current_api_key: ContextVar[str | None] = ContextVar("current_api_key", default=None)


class BearerAuthMiddleware:
    """Starlette middleware that extracts Bearer token from Authorization header
    and stores it in a contextvar for MCP tools to access."""

    # Paths that don't require authentication
    PUBLIC_PATHS = {"/auth/strava", "/auth/callback"}

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        path = request.url.path

        # Skip auth for public paths
        if path in self.PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        # Extract Bearer token
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            api_key = auth_header[7:]
            token = current_api_key.set(api_key)
            try:
                await self.app(scope, receive, send)
            finally:
                current_api_key.reset(token)
        else:
            # No auth header — let the request through (MCP protocol handles its own init)
            # Tools will fail gracefully if no api_key is set
            await self.app(scope, receive, send)
