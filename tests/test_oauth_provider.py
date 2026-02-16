"""Tests for the MCP OAuth provider."""

import os
import tempfile
import time

import pytest
import pytest_asyncio
from mcp.server.auth.provider import AuthorizationCode, RefreshToken
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from strava_mcp.config import StravaSettings
from strava_mcp.db import UserDB
from strava_mcp.oauth_provider import StravaOAuthProvider


@pytest_asyncio.fixture
async def db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        user_db = UserDB(db_path)
        await user_db.init()
        yield user_db
        await user_db.close()


@pytest.fixture
def settings():
    return StravaSettings(
        client_id="test_client_id",
        client_secret="test_client_secret",
        server_base_url="https://my-server.com",
    )


@pytest.fixture
def provider(settings, db):
    return StravaOAuthProvider(settings, db)


@pytest.fixture
def client_info():
    return OAuthClientInformationFull(
        client_id="test-client-123",
        client_secret="test-secret",
        redirect_uris=[AnyUrl("https://example.com/callback")],
    )


# --- Client registration ---


@pytest.mark.asyncio
async def test_register_and_get_client(provider, client_info):
    await provider.register_client(client_info)
    result = await provider.get_client(client_info.client_id)
    assert result is not None
    assert result.client_id == client_info.client_id


@pytest.mark.asyncio
async def test_get_client_not_found(provider):
    result = await provider.get_client("nonexistent")
    assert result is None


# --- Authorize ---


@pytest.mark.asyncio
async def test_authorize_returns_strava_url(provider, client_info):
    from mcp.server.auth.provider import AuthorizationParams

    params = AuthorizationParams(
        state="mcp-state-123",
        scopes=["claudeai"],
        code_challenge="challenge123",
        redirect_uri=AnyUrl("https://example.com/callback"),
        redirect_uri_provided_explicitly=True,
        resource=None,
    )
    url = await provider.authorize(client_info, params)
    assert "strava.com/oauth/authorize" in url
    assert "client_id=test_client_id" in url
    assert "state=" in url


# --- Token exchange flow ---


@pytest.mark.asyncio
async def test_exchange_authorization_code(provider, db, client_info):
    # Create a user first
    api_key = await db.upsert_user(
        strava_athlete_id=12345,
        access_token="strava_access",
        refresh_token="strava_refresh",
        token_expires_at=9999999999.0,
    )

    # Store an auth code
    await db.save_authorization_code(
        code="test-auth-code",
        client_id=client_info.client_id,
        api_key=api_key,
        code_challenge="challenge",
        redirect_uri="https://example.com/callback",
        redirect_uri_provided_explicitly=True,
        scopes=["claudeai"],
        resource=None,
        expires_at=time.time() + 600,
    )

    auth_code = AuthorizationCode(
        code="test-auth-code",
        client_id=client_info.client_id,
        code_challenge="challenge",
        redirect_uri=AnyUrl("https://example.com/callback"),
        redirect_uri_provided_explicitly=True,
        scopes=["claudeai"],
        expires_at=time.time() + 600,
        resource=None,
    )

    token = await provider.exchange_authorization_code(client_info, auth_code)
    assert token.access_token == api_key
    assert token.token_type.lower() == "bearer"
    assert token.refresh_token is not None

    # Auth code should be deleted (single-use)
    assert await db.get_authorization_code("test-auth-code") is None


@pytest.mark.asyncio
async def test_load_access_token(provider, db):
    api_key = await db.upsert_user(
        strava_athlete_id=12345,
        access_token="strava_access",
        refresh_token="strava_refresh",
        token_expires_at=9999999999.0,
    )

    result = await provider.load_access_token(api_key)
    assert result is not None
    assert result.token == api_key
    assert "claudeai" in result.scopes


@pytest.mark.asyncio
async def test_load_access_token_invalid(provider):
    result = await provider.load_access_token("invalid-key")
    assert result is None


@pytest.mark.asyncio
async def test_load_authorization_code_expired(provider, db, client_info):
    api_key = await db.upsert_user(
        strava_athlete_id=12345,
        access_token="a",
        refresh_token="r",
        token_expires_at=9999999999.0,
    )

    await db.save_authorization_code(
        code="expired-code",
        client_id=client_info.client_id,
        api_key=api_key,
        code_challenge="challenge",
        redirect_uri="https://example.com/callback",
        redirect_uri_provided_explicitly=True,
        scopes=["claudeai"],
        resource=None,
        expires_at=time.time() - 1,  # expired
    )

    result = await provider.load_authorization_code(client_info, "expired-code")
    assert result is None


@pytest.mark.asyncio
async def test_load_authorization_code_wrong_client(provider, db, client_info):
    api_key = await db.upsert_user(
        strava_athlete_id=12345,
        access_token="a",
        refresh_token="r",
        token_expires_at=9999999999.0,
    )

    await db.save_authorization_code(
        code="other-client-code",
        client_id="other-client",
        api_key=api_key,
        code_challenge="challenge",
        redirect_uri="https://example.com/callback",
        redirect_uri_provided_explicitly=True,
        scopes=["claudeai"],
        resource=None,
        expires_at=time.time() + 600,
    )

    result = await provider.load_authorization_code(client_info, "other-client-code")
    assert result is None


# --- Refresh token flow ---


@pytest.mark.asyncio
async def test_refresh_token_flow(provider, db, client_info):
    api_key = await db.upsert_user(
        strava_athlete_id=12345,
        access_token="strava_access",
        refresh_token="strava_refresh",
        token_expires_at=9999999999.0,
    )

    # Save a refresh token
    await db.save_oauth_token(
        token="refresh-token-1",
        token_type="refresh",
        client_id=client_info.client_id,
        api_key=api_key,
        scopes=["claudeai"],
        resource=None,
        expires_at=None,
    )

    # Load it
    rt = await provider.load_refresh_token(client_info, "refresh-token-1")
    assert rt is not None
    assert rt.token == "refresh-token-1"

    # Exchange it
    new_token = await provider.exchange_refresh_token(client_info, rt, scopes=["claudeai"])
    assert new_token.access_token == api_key
    assert new_token.refresh_token != "refresh-token-1"  # new refresh token

    # Old refresh token should be revoked
    old = await db.get_oauth_token("refresh-token-1")
    assert old is None  # revoked tokens are filtered out


@pytest.mark.asyncio
async def test_revoke_refresh_token(provider, db, client_info):
    api_key = await db.upsert_user(
        strava_athlete_id=12345,
        access_token="a",
        refresh_token="r",
        token_expires_at=9999999999.0,
    )

    await db.save_oauth_token(
        token="rt-to-revoke",
        token_type="refresh",
        client_id=client_info.client_id,
        api_key=api_key,
        scopes=["claudeai"],
        resource=None,
        expires_at=None,
    )

    rt = RefreshToken(
        token="rt-to-revoke",
        client_id=client_info.client_id,
        scopes=["claudeai"],
    )
    await provider.revoke_token(rt)

    assert await db.get_oauth_token("rt-to-revoke") is None
