import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from strava_mcp.config import StravaSettings
from strava_mcp.db import UserDB
from strava_mcp.middleware import current_api_key
from strava_mcp.service import StravaService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Initialize settings eagerly (reads env vars, no async needed)
try:
    settings = StravaSettings()
    if not settings.client_id:
        raise ValueError("STRAVA_CLIENT_ID environment variable is not set")
    if not settings.client_secret:
        raise ValueError("STRAVA_CLIENT_SECRET environment variable is not set")
    logger.info("Loaded Strava API settings")
except Exception as e:
    logger.error(f"Failed to load Strava API settings: {str(e)}")
    raise

# Create DB instance (async init happens in lifespan)
db = UserDB(settings.database_path)


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Initialize the database and provide settings/db to tools.

    Args:
        server: The FastMCP server instance

    Yields:
        The lifespan context containing settings and database
    """
    await db.init()
    logger.info("User database initialized")

    try:
        yield {"settings": settings, "db": db}
    finally:
        await db.close()
        logger.info("Database closed")


# Create the MCP server
# Disable DNS rebinding protection — the server runs behind a reverse proxy/tunnel
mcp = FastMCP(
    "Strava",
    instructions="MCP server for interacting with the Strava API. "
    "Users must first authenticate at /auth/strava to get an API key.",
    lifespan=lifespan,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


async def _get_service(ctx: Context) -> StravaService:
    """Resolve a per-user StravaService from the MCP context.

    Uses the API key from the Authorization header (stored in contextvar
    by the BearerAuthMiddleware) to look up the user's Strava tokens.
    """
    if not ctx.request_context.lifespan_context:
        raise ValueError("Lifespan context not available")

    settings: StravaSettings = ctx.request_context.lifespan_context["settings"]
    db: UserDB = ctx.request_context.lifespan_context["db"]

    api_key = current_api_key.get()
    if not api_key:
        raise ValueError(
            "No API key provided. Please authenticate at /auth/strava "
            "and include your API key in the Authorization header: Bearer <api-key>"
        )

    user = await db.get_user_by_api_key(api_key)
    if not user:
        raise ValueError("Invalid API key. Please re-authenticate at /auth/strava")

    return StravaService.for_user(settings, user, db)


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
        service = await _get_service(ctx)
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
        service = await _get_service(ctx)
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
        service = await _get_service(ctx)
        segments = await service.get_activity_segments(activity_id)
        return [segment.model_dump() for segment in segments]
    except Exception as e:
        logger.error(f"Error in get_activity_segments tool: {str(e)}")
        raise
