import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl

from strava_mcp.config import StravaSettings
from strava_mcp.db import UserDB
from strava_mcp.middleware import current_api_key
from strava_mcp.oauth_provider import StravaOAuthProvider
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

# Create DB instance (async init happens in main.py before app starts)
db = UserDB(settings.database_path)

# Create OAuth provider
oauth_provider = StravaOAuthProvider(settings, db)

# Auth settings for MCP OAuth
auth_settings = AuthSettings(
    issuer_url=AnyHttpUrl(settings.server_base_url),
    resource_server_url=AnyHttpUrl(f"{settings.server_base_url.rstrip('/')}/mcp"),
    required_scopes=["claudeai"],
    client_registration_options=ClientRegistrationOptions(
        enabled=True,
        valid_scopes=["claudeai"],
        default_scopes=["claudeai"],
    ),
    revocation_options=RevocationOptions(enabled=True),
)


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Initialize the database and provide settings/db to tools.

    For HTTP transport, the DB is pre-initialized by main.py before the app
    starts, so this lifespan must not close it (it runs per MCP session, and
    closing would set _db=None, breaking subsequent requests).

    For stdio transport, this lifespan owns the full DB lifecycle.

    Args:
        server: The FastMCP server instance

    Yields:
        The lifespan context containing settings and database
    """
    db_owned_here = db._db is None
    if db_owned_here:
        await db.init()
        logger.info("User database initialized")

    try:
        yield {"settings": settings, "db": db}
    finally:
        if db_owned_here:
            await db.close()
            logger.info("Database closed")


# Create the MCP server with OAuth support
# Disable DNS rebinding protection — the server runs behind a reverse proxy/tunnel
mcp = FastMCP(
    "Strava",
    instructions="MCP server for interacting with the Strava API. "
    "Users must first authenticate via the OAuth flow to access tools.",
    lifespan=lifespan,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    auth=auth_settings,
    auth_server_provider=oauth_provider,
)


async def _get_service(ctx: Context) -> StravaService:
    """Resolve a per-user StravaService from the MCP context.

    Reads the API key from the MCP auth context (set by the library's
    AuthContextMiddleware) with fallback to legacy BearerAuthMiddleware.
    """
    if not ctx.request_context.lifespan_context:
        raise ValueError("Lifespan context not available")

    ctx_settings: StravaSettings = ctx.request_context.lifespan_context["settings"]
    ctx_db: UserDB = ctx.request_context.lifespan_context["db"]

    # Try MCP OAuth auth context first (set by MCP library's AuthContextMiddleware)
    api_key: str | None = None
    auth_context = auth_context_var.get(None)
    if auth_context and auth_context.access_token:
        api_key = auth_context.access_token.token

    # Fallback to legacy BearerAuthMiddleware contextvar
    if not api_key:
        api_key = current_api_key.get()

    if not api_key:
        raise ValueError(
            "No API key provided. Please authenticate via the OAuth flow "
            "or include your API key in the Authorization header: Bearer <api-key>"
        )

    user = await ctx_db.get_user_by_api_key(api_key)
    if not user:
        raise ValueError("Invalid API key. Please re-authenticate.")

    return StravaService.for_user(ctx_settings, user, ctx_db)


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


@mcp.tool()
async def get_rate_limit_status(ctx: Context) -> dict:
    """Get the current Strava API rate limit status.

    Returns usage and limits from the most recent API call.
    Use this to check remaining quota before making multiple requests.

    Args:
        ctx: The MCP request context

    Returns:
        Rate limit status with short-term (15-min) and daily usage/limits
    """
    try:
        service = await _get_service(ctx)
        rl = service.get_rate_limits()
        return {
            "short_term": {
                "usage": rl.short_usage,
                "limit": rl.short_limit,
                "remaining": rl.short_limit - rl.short_usage,
            },
            "daily": {
                "usage": rl.daily_usage,
                "limit": rl.daily_limit,
                "remaining": rl.daily_limit - rl.daily_usage,
            },
        }
    except Exception as e:
        logger.error(f"Error in get_rate_limit_status tool: {str(e)}")
        raise
