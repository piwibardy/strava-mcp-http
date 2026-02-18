import argparse
import logging

import anyio
import uvicorn

from strava_mcp.auth import create_auth_routes
from strava_mcp.server import db, mcp, settings

logger = logging.getLogger(__name__)


def main():
    """Run the Strava MCP server."""
    parser = argparse.ArgumentParser(description="Strava MCP Server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    logger.info("Starting MCP server with transport=%s", args.transport)

    if args.transport == "streamable-http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port

        async def run() -> None:
            # Initialize the database before the app starts so that the MCP
            # OAuth middleware can use it from the very first request.
            # The lifespan in server.py detects this and skips init/close,
            # since it runs per MCP session and must not own the DB lifecycle.
            await db.init()
            logger.info("User database initialized")

            try:
                # Build the MCP Starlette app (includes OAuth endpoints + auth middleware)
                starlette_app = mcp.streamable_http_app()

                # Inject Strava auth routes at the beginning of the route table
                # These are public (not auth-protected) and handle the Strava OAuth flow
                auth_routes = create_auth_routes(settings, db)
                starlette_app.routes[0:0] = auth_routes

                config = uvicorn.Config(
                    starlette_app,
                    host=args.host,
                    port=args.port,
                    log_level="info",
                )
                server = uvicorn.Server(config)
                await server.serve()
            finally:
                await db.close()
                logger.info("Database closed")

        anyio.run(run)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
