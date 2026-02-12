"""Tests for the user database module."""

import json
import os
import tempfile
import time

import pytest
import pytest_asyncio

from strava_mcp.db import UserDB


@pytest_asyncio.fixture
async def db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        user_db = UserDB(db_path)
        await user_db.init()
        yield user_db
        await user_db.close()


@pytest.mark.asyncio
async def test_init_creates_table(db):
    """Test that init creates the users table."""
    conn = db._ensure_db()
    cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    row = await cursor.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_upsert_user_creates_new(db):
    """Test creating a new user."""
    api_key = await db.upsert_user(
        strava_athlete_id=12345,
        access_token="access_123",
        refresh_token="refresh_123",
        token_expires_at=9999999999.0,
    )
    assert api_key is not None
    assert len(api_key) == 36  # UUID format


@pytest.mark.asyncio
async def test_upsert_user_updates_existing(db):
    """Test that upsert returns same api_key for same athlete."""
    api_key_1 = await db.upsert_user(
        strava_athlete_id=12345,
        access_token="access_1",
        refresh_token="refresh_1",
        token_expires_at=1000.0,
    )
    api_key_2 = await db.upsert_user(
        strava_athlete_id=12345,
        access_token="access_2",
        refresh_token="refresh_2",
        token_expires_at=2000.0,
    )
    assert api_key_1 == api_key_2

    # Verify tokens were updated
    user = await db.get_user_by_api_key(api_key_1)
    assert user is not None
    assert user.access_token == "access_2"
    assert user.refresh_token == "refresh_2"
    assert user.token_expires_at == 2000.0


@pytest.mark.asyncio
async def test_get_user_by_api_key(db):
    """Test getting a user by API key."""
    api_key = await db.upsert_user(
        strava_athlete_id=12345,
        access_token="access_123",
        refresh_token="refresh_123",
        token_expires_at=9999999999.0,
    )

    user = await db.get_user_by_api_key(api_key)
    assert user is not None
    assert user.api_key == api_key
    assert user.strava_athlete_id == 12345
    assert user.access_token == "access_123"
    assert user.refresh_token == "refresh_123"


@pytest.mark.asyncio
async def test_get_user_by_api_key_not_found(db):
    """Test getting a non-existent user."""
    user = await db.get_user_by_api_key("non-existent-key")
    assert user is None


@pytest.mark.asyncio
async def test_update_user_tokens(db):
    """Test updating user tokens."""
    api_key = await db.upsert_user(
        strava_athlete_id=12345,
        access_token="old_access",
        refresh_token="old_refresh",
        token_expires_at=1000.0,
    )

    await db.update_user_tokens(
        api_key=api_key,
        access_token="new_access",
        refresh_token="new_refresh",
        token_expires_at=2000.0,
    )

    user = await db.get_user_by_api_key(api_key)
    assert user is not None
    assert user.access_token == "new_access"
    assert user.refresh_token == "new_refresh"
    assert user.token_expires_at == 2000.0


@pytest.mark.asyncio
async def test_ensure_db_raises_before_init():
    """Test that _ensure_db raises if not initialized."""
    db = UserDB("/tmp/nonexistent.db")
    with pytest.raises(RuntimeError, match="Database not initialized"):
        db._ensure_db()


# --- OAuth tables ---


@pytest.mark.asyncio
async def test_init_creates_oauth_tables(db):
    """Test that init creates all OAuth tables."""
    conn = db._ensure_db()
    for table in ["oauth_clients", "oauth_pending_sessions", "oauth_authorization_codes", "oauth_tokens"]:
        cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        row = await cursor.fetchone()
        assert row is not None, f"Table {table} not found"


@pytest.mark.asyncio
async def test_oauth_client_crud(db):
    """Test saving and retrieving an OAuth client."""
    info = {"client_id": "c1", "client_secret": "s1", "redirect_uris": []}
    await db.save_oauth_client("c1", "s1", json.dumps(info))

    result = await db.get_oauth_client("c1")
    assert result is not None
    assert result["client_id"] == "c1"

    assert await db.get_oauth_client("nonexistent") is None


@pytest.mark.asyncio
async def test_pending_session_crud(db):
    """Test pending session save, get, delete."""
    await db.save_pending_session(
        session_id="sess-1",
        client_id="c1",
        mcp_state="state-1",
        code_challenge="challenge",
        redirect_uri="https://example.com/cb",
        redirect_uri_provided_explicitly=True,
        scopes=["claudeai"],
        resource=None,
    )

    session = await db.get_pending_session("sess-1")
    assert session is not None
    assert session["client_id"] == "c1"
    assert session["mcp_state"] == "state-1"

    await db.delete_pending_session("sess-1")
    assert await db.get_pending_session("sess-1") is None


@pytest.mark.asyncio
async def test_authorization_code_crud(db):
    """Test authorization code save, get, delete."""

    await db.save_authorization_code(
        code="code-1",
        client_id="c1",
        api_key="key-1",
        code_challenge="challenge",
        redirect_uri="https://example.com/cb",
        redirect_uri_provided_explicitly=True,
        scopes=["claudeai"],
        resource=None,
        expires_at=time.time() + 600,
    )

    code = await db.get_authorization_code("code-1")
    assert code is not None
    assert code["client_id"] == "c1"
    assert code["api_key"] == "key-1"

    await db.delete_authorization_code("code-1")
    assert await db.get_authorization_code("code-1") is None


@pytest.mark.asyncio
async def test_oauth_token_crud(db):
    """Test OAuth token save, get, revoke."""
    await db.save_oauth_token(
        token="tok-1",
        token_type="refresh",
        client_id="c1",
        api_key="key-1",
        scopes=["claudeai"],
        resource=None,
        expires_at=None,
    )

    tok = await db.get_oauth_token("tok-1")
    assert tok is not None
    assert tok["token_type"] == "refresh"

    await db.revoke_oauth_token("tok-1")
    assert await db.get_oauth_token("tok-1") is None  # revoked = filtered


@pytest.mark.asyncio
async def test_revoke_tokens_for_client(db):
    """Test revoking all tokens for a user+client."""
    await db.save_oauth_token(
        token="tok-a",
        token_type="refresh",
        client_id="c1",
        api_key="key-1",
        scopes=None,
        resource=None,
        expires_at=None,
    )
    await db.save_oauth_token(
        token="tok-b",
        token_type="refresh",
        client_id="c1",
        api_key="key-1",
        scopes=None,
        resource=None,
        expires_at=None,
    )
    await db.save_oauth_token(
        token="tok-c",
        token_type="refresh",
        client_id="c2",
        api_key="key-1",
        scopes=None,
        resource=None,
        expires_at=None,
    )

    await db.revoke_oauth_tokens_for_client("key-1", "c1")

    assert await db.get_oauth_token("tok-a") is None
    assert await db.get_oauth_token("tok-b") is None
    assert await db.get_oauth_token("tok-c") is not None  # different client
