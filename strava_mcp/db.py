import json
import logging
import os
import uuid
from dataclasses import dataclass

import aiosqlite

logger = logging.getLogger(__name__)


@dataclass
class User:
    """Represents a stored user with Strava tokens."""

    api_key: str
    strava_athlete_id: int
    access_token: str
    refresh_token: str
    token_expires_at: float
    created_at: str


class UserDB:
    """Async SQLite store for user tokens."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Initialize the database and create tables if needed.

        Idempotent: if the database is already initialized, this is a no-op.
        """
        if self._db is not None:
            return
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                api_key TEXT PRIMARY KEY,
                strava_athlete_id INTEGER NOT NULL,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                token_expires_at REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_athlete_id ON users (strava_athlete_id)
        """)
        # OAuth tables
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS oauth_clients (
                client_id TEXT PRIMARY KEY,
                client_secret TEXT,
                client_info_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS oauth_pending_sessions (
                session_id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                mcp_state TEXT,
                code_challenge TEXT NOT NULL,
                redirect_uri TEXT NOT NULL,
                redirect_uri_provided_explicitly INTEGER NOT NULL DEFAULT 1,
                scopes TEXT,
                resource TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS oauth_authorization_codes (
                code TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                api_key TEXT NOT NULL,
                code_challenge TEXT NOT NULL,
                redirect_uri TEXT NOT NULL,
                redirect_uri_provided_explicitly INTEGER NOT NULL DEFAULT 1,
                scopes TEXT,
                resource TEXT,
                expires_at REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                token TEXT PRIMARY KEY,
                token_type TEXT NOT NULL,
                client_id TEXT NOT NULL,
                api_key TEXT NOT NULL,
                scopes TEXT,
                resource TEXT,
                expires_at INTEGER,
                revoked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await self._db.commit()
        logger.info("Database initialized at %s", self.db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    def _ensure_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database not initialized. Call init() first.")
        return self._db

    async def upsert_user(
        self,
        strava_athlete_id: int,
        access_token: str,
        refresh_token: str,
        token_expires_at: float,
    ) -> str:
        """Create or update a user. Returns the API key."""
        db = self._ensure_db()

        # Check if user already exists for this athlete
        cursor = await db.execute(
            "SELECT api_key FROM users WHERE strava_athlete_id = ?",
            (strava_athlete_id,),
        )
        row = await cursor.fetchone()

        if row:
            api_key = row["api_key"]
            await db.execute(
                """UPDATE users
                   SET access_token = ?, refresh_token = ?, token_expires_at = ?
                   WHERE api_key = ?""",
                (access_token, refresh_token, token_expires_at, api_key),
            )
            await db.commit()
            logger.info("Updated tokens for athlete %s", strava_athlete_id)
            return api_key

        api_key = str(uuid.uuid4())
        await db.execute(
            """INSERT INTO users (api_key, strava_athlete_id, access_token, refresh_token, token_expires_at)
               VALUES (?, ?, ?, ?, ?)""",
            (api_key, strava_athlete_id, access_token, refresh_token, token_expires_at),
        )
        await db.commit()
        logger.info("Created user for athlete %s with api_key %s", strava_athlete_id, api_key)
        return api_key

    async def get_user_by_api_key(self, api_key: str) -> User | None:
        """Get a user by their API key."""
        db = self._ensure_db()
        cursor = await db.execute("SELECT * FROM users WHERE api_key = ?", (api_key,))
        row = await cursor.fetchone()
        if not row:
            return None
        return User(
            api_key=row["api_key"],
            strava_athlete_id=row["strava_athlete_id"],
            access_token=row["access_token"],
            refresh_token=row["refresh_token"],
            token_expires_at=row["token_expires_at"],
            created_at=row["created_at"],
        )

    async def update_user_tokens(
        self,
        api_key: str,
        access_token: str,
        refresh_token: str,
        token_expires_at: float,
    ) -> None:
        """Update tokens for an existing user."""
        db = self._ensure_db()
        await db.execute(
            """UPDATE users
               SET access_token = ?, refresh_token = ?, token_expires_at = ?
               WHERE api_key = ?""",
            (access_token, refresh_token, token_expires_at, api_key),
        )
        await db.commit()

    # --- OAuth clients ---

    async def save_oauth_client(self, client_id: str, client_secret: str | None, client_info_json: str) -> None:
        """Store a dynamically registered OAuth client."""
        db = self._ensure_db()
        await db.execute(
            "INSERT INTO oauth_clients (client_id, client_secret, client_info_json) VALUES (?, ?, ?)",
            (client_id, client_secret, client_info_json),
        )
        await db.commit()

    async def get_oauth_client(self, client_id: str) -> dict | None:
        """Get an OAuth client by client_id. Returns parsed JSON info."""
        db = self._ensure_db()
        cursor = await db.execute(
            "SELECT client_info_json FROM oauth_clients WHERE client_id = ?",
            (client_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return json.loads(row["client_info_json"])

    # --- OAuth pending sessions ---

    async def save_pending_session(
        self,
        session_id: str,
        client_id: str,
        mcp_state: str | None,
        code_challenge: str,
        redirect_uri: str,
        redirect_uri_provided_explicitly: bool,
        scopes: list[str] | None,
        resource: str | None,
    ) -> None:
        """Store a pending MCP OAuth session (links /authorize to Strava callback)."""
        db = self._ensure_db()
        # Clean up expired sessions (older than 10 minutes)
        await db.execute("DELETE FROM oauth_pending_sessions WHERE created_at < datetime('now', '-10 minutes')")
        await db.execute(
            """INSERT INTO oauth_pending_sessions
               (session_id, client_id, mcp_state, code_challenge, redirect_uri,
                redirect_uri_provided_explicitly, scopes, resource)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                client_id,
                mcp_state,
                code_challenge,
                redirect_uri,
                1 if redirect_uri_provided_explicitly else 0,
                json.dumps(scopes) if scopes else None,
                resource,
            ),
        )
        await db.commit()

    async def get_pending_session(self, session_id: str) -> dict | None:
        """Get a pending OAuth session by session_id."""
        db = self._ensure_db()
        cursor = await db.execute(
            "SELECT * FROM oauth_pending_sessions WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return dict(row)

    async def delete_pending_session(self, session_id: str) -> None:
        """Delete a pending session after it's been used."""
        db = self._ensure_db()
        await db.execute(
            "DELETE FROM oauth_pending_sessions WHERE session_id = ?",
            (session_id,),
        )
        await db.commit()

    # --- OAuth authorization codes ---

    async def save_authorization_code(
        self,
        code: str,
        client_id: str,
        api_key: str,
        code_challenge: str,
        redirect_uri: str,
        redirect_uri_provided_explicitly: bool,
        scopes: list[str] | None,
        resource: str | None,
        expires_at: float,
    ) -> None:
        """Store an MCP authorization code."""
        db = self._ensure_db()
        await db.execute(
            """INSERT INTO oauth_authorization_codes
               (code, client_id, api_key, code_challenge, redirect_uri,
                redirect_uri_provided_explicitly, scopes, resource, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                code,
                client_id,
                api_key,
                code_challenge,
                redirect_uri,
                1 if redirect_uri_provided_explicitly else 0,
                json.dumps(scopes) if scopes else None,
                resource,
                expires_at,
            ),
        )
        await db.commit()

    async def get_authorization_code(self, code: str) -> dict | None:
        """Get an authorization code record."""
        db = self._ensure_db()
        cursor = await db.execute(
            "SELECT * FROM oauth_authorization_codes WHERE code = ?",
            (code,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return dict(row)

    async def delete_authorization_code(self, code: str) -> None:
        """Delete an authorization code (single-use)."""
        db = self._ensure_db()
        await db.execute(
            "DELETE FROM oauth_authorization_codes WHERE code = ?",
            (code,),
        )
        await db.commit()

    # --- OAuth tokens ---

    async def save_oauth_token(
        self,
        token: str,
        token_type: str,
        client_id: str,
        api_key: str,
        scopes: list[str] | None,
        resource: str | None,
        expires_at: int | None,
    ) -> None:
        """Store an OAuth token (access or refresh)."""
        db = self._ensure_db()
        await db.execute(
            """INSERT INTO oauth_tokens
               (token, token_type, client_id, api_key, scopes, resource, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                token,
                token_type,
                client_id,
                api_key,
                json.dumps(scopes) if scopes else None,
                resource,
                expires_at,
            ),
        )
        await db.commit()

    async def get_oauth_token(self, token: str) -> dict | None:
        """Get an OAuth token record."""
        db = self._ensure_db()
        cursor = await db.execute(
            "SELECT * FROM oauth_tokens WHERE token = ? AND revoked = 0",
            (token,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return dict(row)

    async def revoke_oauth_token(self, token: str) -> None:
        """Mark an OAuth token as revoked."""
        db = self._ensure_db()
        await db.execute(
            "UPDATE oauth_tokens SET revoked = 1 WHERE token = ?",
            (token,),
        )
        await db.commit()

    async def revoke_oauth_tokens_for_client(self, api_key: str, client_id: str) -> None:
        """Revoke all tokens for a given user+client combination."""
        db = self._ensure_db()
        await db.execute(
            "UPDATE oauth_tokens SET revoked = 1 WHERE api_key = ? AND client_id = ?",
            (api_key, client_id),
        )
        await db.commit()
