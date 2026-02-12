import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI
from mcp.server.fastmcp import Context, FastMCP

from strava_mcp.config import StravaSettings
from strava_mcp.service import StravaService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Set up and tear down the Strava service for the MCP server.

    Args:
        server: The FastMCP server instance

    Yields:
        The lifespan context containing the Strava service
    """
    # Load settings from environment variables
    try:
        # Let StravaSettings load values directly from env vars
        settings = StravaSettings()

        if not settings.client_id:
            raise ValueError("STRAVA_CLIENT_ID environment variable is not set")
        if not settings.client_secret:
            raise ValueError("STRAVA_CLIENT_SECRET environment variable is not set")

        logger.info("Loaded Strava API settings")
    except Exception as e:
        logger.error(f"Failed to load Strava API settings: {str(e)}")
        raise

    # FastMCP extends FastAPI, so we can safely cast it for type checking
    fastapi_app = cast(FastAPI, server)

    # Initialize the Strava service with the FastAPI app
    service = StravaService(settings, fastapi_app)
    logger.info("Initialized Strava service")

    # Set up authentication routes and initialize
    await service.initialize()
    logger.info("Service initialization completed")

    try:
        yield {"service": service}
    finally:
        # Clean up resources
        await service.close()
        logger.info("Closed Strava service")


# Create the MCP server
mcp = FastMCP(
    "Strava",
    instructions="MCP server for interacting with the Strava API",
    lifespan=lifespan,
)


@mcp.tool()
async def get_user_activities(
    ctx: Context,
    before: int | None = None,
    after: int | None = None,
    page: int = 1,
    per_page: int = 30,
) -> list[dict]:
    """Get the authenticated user's activities.

    Args:
        ctx: The MCP request context
        before: An epoch timestamp for filtering activities before a certain time
        after: An epoch timestamp for filtering activities after a certain time
        page: Page number
        per_page: Number of items per page

    Returns:
        List of activities
    """
    try:
        # Safely access service from context
        if not ctx.request_context.lifespan_context:
            raise ValueError("Lifespan context not available")

        # Cast service to StravaService to satisfy type checker
        service = cast(StravaService, ctx.request_context.lifespan_context.get("service"))
        if not service:
            raise ValueError("Service not available in context")

        activities = await service.get_activities(before, after, page, per_page)
        return [activity.model_dump() for activity in activities]
    except Exception as e:
        logger.error(f"Error in get_user_activities tool: {str(e)}")
        raise


@mcp.tool()
async def get_activity(
    ctx: Context,
    activity_id: int,
    include_all_efforts: bool = False,
) -> dict:
    """Get details of a specific activity.

    Args:
        ctx: The MCP request context
        activity_id: The ID of the activity
        include_all_efforts: Whether to include all segment efforts

    Returns:
        The activity details
    """
    try:
        # Safely access service from context
        if not ctx.request_context.lifespan_context:
            raise ValueError("Lifespan context not available")

        # Cast service to StravaService to satisfy type checker
        service = cast(StravaService, ctx.request_context.lifespan_context.get("service"))
        if not service:
            raise ValueError("Service not available in context")

        activity = await service.get_activity(activity_id, include_all_efforts)
        return activity.model_dump()
    except Exception as e:
        logger.error(f"Error in get_activity tool: {str(e)}")
        raise


@mcp.tool()
async def get_activity_segments(
    ctx: Context,
    activity_id: int,
) -> list[dict]:
    """Get the segments of a specific activity.

    Args:
        ctx: The MCP request context
        activity_id: The ID of the activity

    Returns:
        List of segment efforts for the activity
    """
    try:
        # Safely access service from context
        if not ctx.request_context.lifespan_context:
            raise ValueError("Lifespan context not available")

        # Cast service to StravaService to satisfy type checker
        service = cast(StravaService, ctx.request_context.lifespan_context.get("service"))
        if not service:
            raise ValueError("Service not available in context")

        segments = await service.get_activity_segments(activity_id)
        return [segment.model_dump() for segment in segments]
    except Exception as e:
        logger.error(f"Error in get_activity_segments tool: {str(e)}")
        raise
