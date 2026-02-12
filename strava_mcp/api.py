import logging
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import anyio
import httpx
from httpx import Response

from strava_mcp.config import StravaSettings
from strava_mcp.models import Activity, DetailedActivity, ErrorResponse, SegmentEffort

logger = logging.getLogger(__name__)

# Callback type for when tokens are refreshed
OnTokenRefreshed = Callable[[str, str, float], Awaitable[None]]


@dataclass
class RateLimitInfo:
    """Tracks Strava API rate limit state from response headers."""

    short_limit: int = 100
    daily_limit: int = 1000
    short_usage: int = 0
    daily_usage: int = 0


class StravaAPI:
    """Client for the Strava API."""

    def __init__(
        self,
        settings: StravaSettings,
        access_token: str | None = None,
        refresh_token: str | None = None,
        token_expires_at: float | None = None,
        on_token_refreshed: OnTokenRefreshed | None = None,
    ):
        """Initialize the Strava API client.

        Args:
            settings: Strava API settings (client_id, client_secret, base_url)
            access_token: User's current access token
            refresh_token: User's refresh token
            token_expires_at: Expiry timestamp for the access token
            on_token_refreshed: Async callback when tokens are refreshed
        """
        self.settings = settings
        self.access_token = access_token
        self.refresh_token = refresh_token or settings.refresh_token
        self.token_expires_at = token_expires_at
        self._on_token_refreshed = on_token_refreshed
        self.rate_limits = RateLimitInfo()
        self._client = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=30.0,
        )

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()

    async def _ensure_token(self) -> str:
        """Ensure we have a valid access token.

        Returns:
            The access token

        Raises:
            Exception: If unable to obtain a valid token
        """
        now = datetime.now().timestamp()

        # If token is still valid, return it
        if self.access_token and self.token_expires_at and now < self.token_expires_at:
            return self.access_token

        if not self.refresh_token:
            raise Exception("No refresh token available. Please authenticate via /auth/strava to get your API key.")

        # Refresh the access token
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://www.strava.com/oauth/token",
                json={
                    "client_id": self.settings.client_id,
                    "client_secret": self.settings.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                },
            )

            if response.status_code != 200:
                error_msg = f"Failed to refresh token: {response.text}"
                logger.error(error_msg)
                raise Exception(error_msg)

            data = response.json()
            self.access_token = data["access_token"]
            self.token_expires_at = data["expires_at"]

            # Update the refresh token if it changed
            if "refresh_token" in data:
                self.refresh_token = data["refresh_token"]

            # Notify callback to persist new tokens
            if self._on_token_refreshed and self.access_token and self.refresh_token:
                await self._on_token_refreshed(
                    self.access_token,
                    self.refresh_token,
                    self.token_expires_at,
                )

            logger.info("Successfully refreshed access token")
            return self.access_token

    def _parse_rate_limits(self, response: Response) -> None:
        """Parse rate limit headers from a Strava API response."""
        try:
            usage = response.headers.get("X-RateLimit-Usage")
            limit = response.headers.get("X-RateLimit-Limit")
            if usage:
                parts = usage.split(",")
                self.rate_limits.short_usage = int(parts[0].strip())
                self.rate_limits.daily_usage = int(parts[1].strip())
            if limit:
                parts = limit.split(",")
                self.rate_limits.short_limit = int(parts[0].strip())
                self.rate_limits.daily_limit = int(parts[1].strip())

            # Warn when approaching limits
            if self.rate_limits.short_limit > 0:
                pct = self.rate_limits.short_usage / self.rate_limits.short_limit
                if pct >= 0.8:
                    logger.warning(
                        "Approaching 15-min rate limit: %d/%d (%.0f%%)",
                        self.rate_limits.short_usage,
                        self.rate_limits.short_limit,
                        pct * 100,
                    )
            if self.rate_limits.daily_limit > 0:
                pct = self.rate_limits.daily_usage / self.rate_limits.daily_limit
                if pct >= 0.8:
                    logger.warning(
                        "Approaching daily rate limit: %d/%d (%.0f%%)",
                        self.rate_limits.daily_usage,
                        self.rate_limits.daily_limit,
                        pct * 100,
                    )
        except (ValueError, IndexError):
            logger.debug("Could not parse rate limit headers")

    @staticmethod
    def _seconds_until_next_window() -> float:
        """Calculate seconds until the next 15-minute window boundary."""
        now = datetime.now(UTC)
        current_minute = now.minute
        next_boundary = (math.ceil((current_minute + 1) / 15) * 15) % 60
        if next_boundary <= current_minute:
            # Wraps to next hour
            wait_minutes = 60 - current_minute + next_boundary
        else:
            wait_minutes = next_boundary - current_minute
        wait_seconds = wait_minutes * 60 - now.second
        return max(1.0, wait_seconds)

    async def _request(self, method: str, endpoint: str, **kwargs) -> Response:
        """Make a request to the Strava API.

        Args:
            method: The HTTP method to use
            endpoint: The API endpoint to call
            **kwargs: Additional arguments to pass to the HTTP client

        Returns:
            The HTTP response

        Raises:
            Exception: If the request fails
        """
        token = await self._ensure_token()
        headers = {"Authorization": f"Bearer {token}"}
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))

        url = endpoint if endpoint.startswith("/") else f"/{endpoint}"

        for attempt in range(2):
            response = await self._client.request(method, url, headers=headers, **kwargs)
            self._parse_rate_limits(response)

            if response.status_code != 429:
                break

            if attempt == 0:
                wait = self._seconds_until_next_window()
                logger.warning(
                    "Rate limited (429). Waiting %.0fs until next 15-min window.",
                    wait,
                )
                await anyio.sleep(wait)
            else:
                raise Exception(
                    f"Strava API rate limit exceeded after retry. "
                    f"Usage: {self.rate_limits.short_usage}/{self.rate_limits.short_limit} (15min), "
                    f"{self.rate_limits.daily_usage}/{self.rate_limits.daily_limit} (daily)"
                )

        if not response.is_success:
            error_msg = f"Strava API request failed: {response.status_code} - {response.text}"
            logger.error(error_msg)

            try:
                error_data = response.json()
                error = ErrorResponse(**error_data)
                raise Exception(f"Strava API error: {error.message} (code: {error.code})")
            except Exception as err:
                msg = f"Strava API failed: {response.status_code} - {response.text[:50]}"
                raise Exception(msg) from err

        return response

    async def get_activities(
        self,
        before: int | None = None,
        after: int | None = None,
        page: int = 1,
        per_page: int = 30,
    ) -> list[Activity]:
        """Get a list of activities for the authenticated athlete.

        Args:
            before: An epoch timestamp for filtering activities before a certain time
            after: An epoch timestamp for filtering activities after a certain time
            page: Page number
            per_page: Number of items per page

        Returns:
            List of activities
        """
        params = {"page": page, "per_page": per_page}
        if before:
            params["before"] = before
        if after:
            params["after"] = after

        response = await self._request("GET", "/athlete/activities", params=params)
        data = response.json()

        return [Activity(**activity) for activity in data]

    async def get_activity(self, activity_id: int, include_all_efforts: bool = False) -> DetailedActivity:
        """Get a specific activity.

        Args:
            activity_id: The ID of the activity
            include_all_efforts: Whether to include all segment efforts

        Returns:
            The activity details
        """
        params = {}
        if include_all_efforts:
            params["include_all_efforts"] = "true"

        response = await self._request("GET", f"/activities/{activity_id}", params=params)
        data = response.json()

        return DetailedActivity(**data)

    async def get_activity_segments(self, activity_id: int) -> list[SegmentEffort]:
        """Get segments from a specific activity.

        Args:
            activity_id: The ID of the activity

        Returns:
            List of segment efforts for the activity
        """
        activity = await self.get_activity(activity_id, include_all_efforts=True)

        if not activity.segment_efforts:
            return []

        # Add missing required fields before validation
        segment_efforts = []
        for effort in activity.segment_efforts:
            # Add activity_id which is required by the model
            effort["activity_id"] = activity_id
            # Add segment_id which is required by the model
            effort["segment_id"] = effort["segment"]["id"]
            # Add total_elevation_gain to the segment if it's missing
            if "total_elevation_gain" not in effort["segment"]:
                # Calculate from elevation high and low or set to 0
                elev_high = effort["segment"].get("elevation_high", 0)
                elev_low = effort["segment"].get("elevation_low", 0)
                effort["segment"]["total_elevation_gain"] = max(0, elev_high - elev_low)

            segment_efforts.append(SegmentEffort.model_validate(effort))

        return segment_efforts
