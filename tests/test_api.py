import os
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from strava_mcp.api import StravaAPI
from strava_mcp.config import StravaSettings
from strava_mcp.models import Activity, DetailedActivity


@pytest.fixture
def settings():
    return StravaSettings(
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
        base_url="https://www.strava.com/api/v3",
    )


@pytest.fixture
def mock_response():
    mock = MagicMock()
    mock.is_success = True
    mock.json = MagicMock(return_value={})
    mock.status_code = 200
    return mock


@pytest.fixture
def api(settings):
    api = StravaAPI(
        settings,
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        token_expires_at=datetime.now().timestamp() + 3600,
    )
    api._client = AsyncMock()
    return api


@pytest.mark.asyncio
async def test_ensure_token_valid(api):
    token = await api._ensure_token()
    assert token == "test_access_token"


@pytest.mark.asyncio
async def test_ensure_token_refresh(settings):
    with patch("httpx.AsyncClient") as mock_client:
        mock_instance = mock_client.return_value.__aenter__.return_value
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access_token",
            "expires_at": datetime.now().timestamp() + 3600,
        }
        mock_instance.post.return_value = mock_response

        api = StravaAPI(
            settings,
            access_token="old_access_token",
            refresh_token="test_refresh_token",
            token_expires_at=datetime.now().timestamp() - 3600,
        )

        token = await api._ensure_token()
        assert token == "new_access_token"

        mock_instance.post.assert_called_once()
        args, kwargs = mock_instance.post.call_args
        assert args[0] == "https://www.strava.com/oauth/token"
        assert kwargs["json"]["client_id"] == "test_client_id"
        assert kwargs["json"]["client_secret"] == "test_client_secret"
        assert kwargs["json"]["refresh_token"] == "test_refresh_token"
        assert kwargs["json"]["grant_type"] == "refresh_token"


@pytest.mark.asyncio
async def test_ensure_token_refresh_calls_callback(settings):
    """Test that on_token_refreshed callback is called after refresh."""
    callback = AsyncMock()

    with patch("httpx.AsyncClient") as mock_client:
        mock_instance = mock_client.return_value.__aenter__.return_value
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_at": 9999999999.0,
        }
        mock_instance.post.return_value = mock_response

        api = StravaAPI(
            settings,
            access_token="old",
            refresh_token="old_refresh",
            token_expires_at=0.0,
            on_token_refreshed=callback,
        )

        await api._ensure_token()

        callback.assert_called_once_with("new_access", "new_refresh", 9999999999.0)


@pytest.mark.asyncio
async def test_ensure_token_no_refresh_token():
    """Test that missing refresh token raises."""
    with patch.dict(os.environ, {}, clear=True):
        no_token_settings = StravaSettings(
            client_id="test",
            client_secret="test",
            refresh_token=None,
            base_url="https://www.strava.com/api/v3",
        )
        api = StravaAPI(no_token_settings, refresh_token=None)

        with pytest.raises(Exception, match="No refresh token available"):
            await api._ensure_token()


@pytest.mark.asyncio
async def test_get_activities(api, mock_response):
    activity_data = {
        "id": 1234567890,
        "name": "Morning Run",
        "distance": 5000,
        "moving_time": 1200,
        "elapsed_time": 1300,
        "total_elevation_gain": 50,
        "type": "Run",
        "sport_type": "Run",
        "start_date": "2023-01-01T10:00:00Z",
        "start_date_local": "2023-01-01T10:00:00Z",
        "timezone": "Europe/London",
        "achievement_count": 2,
        "kudos_count": 5,
        "comment_count": 0,
        "athlete_count": 1,
        "photo_count": 0,
        "trainer": False,
        "commute": False,
        "manual": False,
        "private": False,
        "flagged": False,
        "average_speed": 4.167,
        "max_speed": 5.3,
        "has_heartrate": True,
        "average_heartrate": 140,
        "max_heartrate": 160,
    }
    mock_response.json.return_value = [activity_data]
    api._client.request.return_value = mock_response

    activities = await api.get_activities()

    api._client.request.assert_called_once()
    args, kwargs = api._client.request.call_args
    assert args[0] == "GET"
    assert args[1] == "/athlete/activities"
    assert kwargs["params"] == {"page": 1, "per_page": 30}

    assert len(activities) == 1
    assert isinstance(activities[0], Activity)
    assert activities[0].id == activity_data["id"]


@pytest.mark.asyncio
async def test_get_activity(api, mock_response):
    activity_data = {
        "id": 1234567890,
        "name": "Morning Run",
        "distance": 5000,
        "moving_time": 1200,
        "elapsed_time": 1300,
        "total_elevation_gain": 50,
        "type": "Run",
        "sport_type": "Run",
        "start_date": "2023-01-01T10:00:00Z",
        "start_date_local": "2023-01-01T10:00:00Z",
        "timezone": "Europe/London",
        "achievement_count": 2,
        "kudos_count": 5,
        "comment_count": 0,
        "athlete_count": 1,
        "photo_count": 0,
        "trainer": False,
        "commute": False,
        "manual": False,
        "private": False,
        "flagged": False,
        "average_speed": 4.167,
        "max_speed": 5.3,
        "has_heartrate": True,
        "average_heartrate": 140,
        "max_heartrate": 160,
        "athlete": {"id": 123},
        "description": "Test description",
    }
    mock_response.json.return_value = activity_data
    api._client.request.return_value = mock_response

    activity = await api.get_activity(1234567890)

    api._client.request.assert_called_once()
    args, kwargs = api._client.request.call_args
    assert args[0] == "GET"
    assert args[1] == "/activities/1234567890"

    assert isinstance(activity, DetailedActivity)
    assert activity.id == activity_data["id"]
