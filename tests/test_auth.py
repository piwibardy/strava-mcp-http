"""Tests for the multi-tenant auth module."""

from strava_mcp.auth import get_redirect_uri
from strava_mcp.config import StravaSettings


def test_get_redirect_uri():
    """Test building the redirect URI."""
    settings = StravaSettings(
        client_id="test",
        client_secret="test",
        server_base_url="https://my-server.com",
    )
    assert get_redirect_uri(settings) == "https://my-server.com/auth/callback"


def test_get_redirect_uri_strips_trailing_slash():
    """Test that trailing slash is stripped."""
    settings = StravaSettings(
        client_id="test",
        client_secret="test",
        server_base_url="https://my-server.com/",
    )
    assert get_redirect_uri(settings) == "https://my-server.com/auth/callback"
