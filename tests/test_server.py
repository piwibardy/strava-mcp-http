from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from strava_mcp.db import User
from strava_mcp.middleware import current_api_key
from strava_mcp.models import Activity, DetailedActivity, Segment, SegmentEffort


class MockContext:
    """Mock MCP context for testing."""

    def __init__(self, settings, db):
        self.request_context = MagicMock()
        self.request_context.lifespan_context = {"settings": settings, "db": db}


@pytest.fixture
def mock_settings():
    mock = MagicMock()
    mock.client_id = "test_client_id"
    mock.client_secret = "test_client_secret"
    mock.base_url = "https://www.strava.com/api/v3"
    return mock


@pytest.fixture
def mock_db():
    mock = AsyncMock()
    return mock


@pytest.fixture
def mock_user():
    return User(
        api_key="test-api-key",
        strava_athlete_id=12345,
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        token_expires_at=9999999999.0,
        created_at="2023-01-01T00:00:00",
    )


@pytest.fixture
def mock_ctx(mock_settings, mock_db):
    return MockContext(mock_settings, mock_db)


@pytest.mark.asyncio
async def test_get_user_activities(mock_ctx, mock_db, mock_user):
    mock_db.get_user_by_api_key.return_value = mock_user

    mock_activity = Activity(
        id=1234567890,
        name="Morning Run",
        distance=5000,
        moving_time=1200,
        elapsed_time=1300,
        total_elevation_gain=50,
        type="Run",
        sport_type="Run",
        start_date=datetime.fromisoformat("2023-01-01T10:00:00+00:00"),
        start_date_local=datetime.fromisoformat("2023-01-01T10:00:00+00:00"),
        timezone="Europe/London",
        achievement_count=2,
        kudos_count=5,
        comment_count=0,
        athlete_count=1,
        photo_count=0,
        trainer=False,
        commute=False,
        manual=False,
        private=False,
        flagged=False,
        average_speed=4.167,
        max_speed=5.3,
        has_heartrate=True,
        average_heartrate=140,
        max_heartrate=160,
        map=None,
        workout_type=None,
        elev_high=None,
        elev_low=None,
    )

    # Set the contextvar and mock the service
    token = current_api_key.set("test-api-key")
    try:
        with patch("strava_mcp.server.StravaService") as mock_service_cls:
            mock_service = AsyncMock()
            mock_service.get_activities.return_value = [mock_activity]
            mock_service_cls.for_user.return_value = mock_service

            from strava_mcp.server import get_user_activities

            result = await get_user_activities(mock_ctx)

            mock_service.get_activities.assert_called_once_with(None, None, 1, 30)
            assert len(result) == 1
            assert result[0]["id"] == mock_activity.id
    finally:
        current_api_key.reset(token)


@pytest.mark.asyncio
async def test_get_activity(mock_ctx, mock_db, mock_user):
    mock_db.get_user_by_api_key.return_value = mock_user

    mock_activity = DetailedActivity(
        id=1234567890,
        name="Morning Run",
        distance=5000,
        moving_time=1200,
        elapsed_time=1300,
        total_elevation_gain=50,
        type="Run",
        sport_type="Run",
        start_date=datetime.fromisoformat("2023-01-01T10:00:00+00:00"),
        start_date_local=datetime.fromisoformat("2023-01-01T10:00:00+00:00"),
        timezone="Europe/London",
        achievement_count=2,
        kudos_count=5,
        comment_count=0,
        athlete_count=1,
        photo_count=0,
        trainer=False,
        commute=False,
        manual=False,
        private=False,
        flagged=False,
        average_speed=4.167,
        max_speed=5.3,
        has_heartrate=True,
        average_heartrate=140,
        max_heartrate=160,
        athlete={"id": 123},
        description="Test description",
        map=None,
        workout_type=None,
        elev_high=None,
        elev_low=None,
        calories=None,
        segment_efforts=None,
        splits_metric=None,
        splits_standard=None,
        best_efforts=None,
        photos=None,
        gear=None,
        device_name=None,
    )

    token = current_api_key.set("test-api-key")
    try:
        with patch("strava_mcp.server.StravaService") as mock_service_cls:
            mock_service = AsyncMock()
            mock_service.get_activity.return_value = mock_activity
            mock_service_cls.for_user.return_value = mock_service

            from strava_mcp.server import get_activity

            result = await get_activity(mock_ctx, 1234567890)

            mock_service.get_activity.assert_called_once_with(1234567890, False)
            assert result["id"] == mock_activity.id
    finally:
        current_api_key.reset(token)


@pytest.mark.asyncio
async def test_get_activity_segments(mock_ctx, mock_db, mock_user):
    mock_db.get_user_by_api_key.return_value = mock_user

    mock_segment = SegmentEffort(
        id=67890,
        activity_id=1234567890,
        segment_id=12345,
        name="Test Segment",
        elapsed_time=180,
        moving_time=180,
        start_date=datetime.fromisoformat("2023-01-01T10:05:00+00:00"),
        start_date_local=datetime.fromisoformat("2023-01-01T10:05:00+00:00"),
        distance=1000,
        athlete={"id": 123},
        segment=Segment(
            id=12345,
            name="Test Segment",
            activity_type="Run",
            distance=1000,
            average_grade=5.0,
            maximum_grade=10.0,
            elevation_high=200,
            elevation_low=150,
            total_elevation_gain=50,
            start_latlng=[51.5, -0.1],
            end_latlng=[51.5, -0.2],
            climb_category=0,
            private=False,
            starred=False,
            city=None,
            state=None,
            country=None,
        ),
        average_watts=None,
        device_watts=None,
        average_heartrate=None,
        max_heartrate=None,
        pr_rank=None,
        achievements=None,
    )

    token = current_api_key.set("test-api-key")
    try:
        with patch("strava_mcp.server.StravaService") as mock_service_cls:
            mock_service = AsyncMock()
            mock_service.get_activity_segments.return_value = [mock_segment]
            mock_service_cls.for_user.return_value = mock_service

            from strava_mcp.server import get_activity_segments

            result = await get_activity_segments(mock_ctx, 1234567890)

            mock_service.get_activity_segments.assert_called_once_with(1234567890)
            assert len(result) == 1
            assert result[0]["id"] == mock_segment.id
    finally:
        current_api_key.reset(token)


@pytest.mark.asyncio
async def test_no_api_key_raises(mock_ctx):
    """Test that missing API key raises an error."""
    from strava_mcp.server import _get_service

    with pytest.raises(ValueError, match="No API key provided"):
        await _get_service(mock_ctx)


@pytest.mark.asyncio
async def test_invalid_api_key_raises(mock_ctx, mock_db):
    """Test that invalid API key raises an error."""
    mock_db.get_user_by_api_key.return_value = None

    token = current_api_key.set("invalid-key")
    try:
        from strava_mcp.server import _get_service

        with pytest.raises(ValueError, match="Invalid API key"):
            await _get_service(mock_ctx)
    finally:
        current_api_key.reset(token)
