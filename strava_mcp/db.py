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
        """Initialize the database and create tables if needed."""
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
