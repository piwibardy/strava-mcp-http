import logging

from strava_mcp.api import RateLimitInfo, StravaAPI
from strava_mcp.config import StravaSettings
from strava_mcp.db import User, UserDB
from strava_mcp.models import Activity, DetailedActivity, SegmentEffort

logger = logging.getLogger(__name__)


class StravaService:
    """Service for interacting with the Strava API."""

    def __init__(self, api: StravaAPI):
        """Initialize the Strava service.

        Args:
            api: Configured StravaAPI client
        """
        self.api = api

    async def close(self):
        """Close the API client."""
        await self.api.close()

    @staticmethod
    def for_user(settings: StravaSettings, user: User, db: UserDB) -> "StravaService":
        """Create a StravaService for a specific user.

        Args:
            settings: App-level settings (client_id, client_secret)
            user: User with Strava tokens
            db: Database to persist refreshed tokens
        """

        async def on_token_refreshed(access_token: str, refresh_token: str, expires_at: float) -> None:
            await db.update_user_tokens(user.api_key, access_token, refresh_token, expires_at)

        api = StravaAPI(
            settings=settings,
            access_token=user.access_token,
            refresh_token=user.refresh_token,
            token_expires_at=user.token_expires_at,
            on_token_refreshed=on_token_refreshed,
        )
        return StravaService(api)

    async def get_activities(
        self,
        before: int | None = None,
        after: int | None = None,
        page: int = 1,
        per_page: int = 30,
    ) -> list[Activity]:
        """Get a list of activities for the authenticated athlete."""
        try:
            logger.info("Getting activities for authenticated athlete")
            activities = await self.api.get_activities(before, after, page, per_page)
            logger.info(f"Retrieved {len(activities)} activities")
            return activities
        except Exception as e:
            logger.error(f"Error getting activities: {str(e)}")
            raise

    async def get_activity(self, activity_id: int, include_all_efforts: bool = False) -> DetailedActivity:
        """Get a specific activity."""
        try:
            logger.info(f"Getting activity {activity_id}")
            activity = await self.api.get_activity(activity_id, include_all_efforts)
            logger.info(f"Retrieved activity: {activity.name}")
            return activity
        except Exception as e:
            logger.error(f"Error getting activity {activity_id}: {str(e)}")
            raise

    def get_rate_limits(self) -> RateLimitInfo:
        """Return the current rate limit state from the last API response."""
        return self.api.rate_limits

    async def get_activity_segments(self, activity_id: int) -> list[SegmentEffort]:
        """Get segments from a specific activity."""
        try:
            logger.info(f"Getting segments for activity {activity_id}")
            segments = await self.api.get_activity_segments(activity_id)
            logger.info(f"Retrieved {len(segments)} segments")
            return segments
        except Exception as e:
            logger.error(f"Error getting segments for activity {activity_id}: {str(e)}")
            raise
