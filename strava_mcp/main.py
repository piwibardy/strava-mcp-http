import argparse
import logging

import anyio
import uvicorn

from strava_mcp.middleware import BearerAuthMiddleware
from strava_mcp.server import mcp

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
            # Get the Starlette app and wrap with auth middleware
            starlette_app = mcp.streamable_http_app()
            app = BearerAuthMiddleware(starlette_app)

            config = uvicorn.Config(
                app,
                host=args.host,
                port=args.port,
                log_level="info",
            )
            server = uvicorn.Server(config)
            await server.serve()

        anyio.run(run)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
