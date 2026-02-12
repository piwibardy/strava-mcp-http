from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from strava_mcp.models import Activity, DetailedActivity, Segment, SegmentEffort
from strava_mcp.service import StravaService


@pytest.fixture
def mock_api():
    mock = AsyncMock()
    mock.get_activities = AsyncMock()
    mock.get_activity = AsyncMock()
    mock.get_activity_segments = AsyncMock()
    return mock


@pytest.fixture
def service(mock_api):
    return StravaService(api=mock_api)


@pytest.mark.asyncio
async def test_get_activities(service, mock_api):
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
    mock_api.get_activities.return_value = [mock_activity]

    activities = await service.get_activities()

    mock_api.get_activities.assert_called_once_with(None, None, 1, 30)
    assert len(activities) == 1
    assert activities[0] == mock_activity


@pytest.mark.asyncio
async def test_get_activity(service, mock_api):
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
    mock_api.get_activity.return_value = mock_activity

    activity = await service.get_activity(1234567890)

    mock_api.get_activity.assert_called_once_with(1234567890, False)
    assert activity == mock_activity


@pytest.mark.asyncio
async def test_get_activity_segments(service, mock_api):
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
    mock_api.get_activity_segments.return_value = [mock_segment]

    segments = await service.get_activity_segments(1234567890)

    mock_api.get_activity_segments.assert_called_once_with(1234567890)
    assert len(segments) == 1
    assert segments[0] == mock_segment
