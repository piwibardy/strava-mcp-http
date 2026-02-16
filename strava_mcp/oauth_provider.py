"""MCP OAuth 2.0 Authorization Server Provider backed by Strava OAuth."""

import json
import logging
import secrets
import time
import uuid
from urllib.parse import urlencode

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from strava_mcp.config import StravaSettings
from strava_mcp.db import UserDB

logger = logging.getLogger(__name__)

STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
STRAVA_SCOPES = "read_all,activity:read,activity:read_all,profile:read_all"
AUTH_CODE_TTL = 600  # 10 minutes
ACCESS_TOKEN_TTL = 86400  # 24 hours (reported in token response)


class StravaOAuthProvider:
    """MCP OAuth Authorization Server Provider.

    Bridges the MCP OAuth flow with Strava's OAuth:
    - /authorize → redirects to Strava OAuth
    - Strava callback → generates MCP auth code → redirects to Claude's redirect_uri
    - /token → exchanges MCP auth code for access token (= user's api_key)
    """

    def __init__(self, settings: StravaSettings, db: UserDB):
        self.settings = settings
        self.db = db

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Retrieve a dynamically registered OAuth client."""
        data = await self.db.get_oauth_client(client_id)
        if not data:
            return None
        return OAuthClientInformationFull(**data)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Register a new OAuth client (dynamic client registration)."""
        if not client_info.client_id:
            raise ValueError("client_id is required for registration")
        await self.db.save_oauth_client(
            client_id=client_info.client_id,
            client_secret=client_info.client_secret,
            client_info_json=client_info.model_dump_json(),
        )
        logger.info("Registered OAuth client: %s", client_info.client_id)

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        """Start the authorization flow by redirecting to Strava OAuth.

        Stores a pending session linking this MCP authorize request to the
        eventual Strava callback, then returns the Strava OAuth URL.
        """
        session_id = str(uuid.uuid4())

        if not client.client_id:
            raise ValueError("client_id is required")
        await self.db.save_pending_session(
            session_id=session_id,
            client_id=client.client_id,
            mcp_state=params.state,
            code_challenge=params.code_challenge,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            scopes=params.scopes,
            resource=params.resource,
        )

        # Build Strava OAuth URL with session_id as state
        strava_params = {
            "client_id": self.settings.client_id,
            "redirect_uri": f"{self.settings.server_base_url.rstrip('/')}/auth/callback",
            "response_type": "code",
            "approval_prompt": "force",
            "scope": STRAVA_SCOPES,
            "state": session_id,
        }
        strava_url = f"{STRAVA_AUTHORIZE_URL}?{urlencode(strava_params)}"
        logger.info("MCP OAuth: redirecting to Strava for session %s", session_id)
        return strava_url

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        """Load an MCP authorization code."""
        data = await self.db.get_authorization_code(authorization_code)
        if not data:
            return None
        if data["client_id"] != client.client_id:
            return None
        if time.time() > data["expires_at"]:
            await self.db.delete_authorization_code(authorization_code)
            return None

        scopes = json.loads(data["scopes"]) if data["scopes"] else []
        return AuthorizationCode(
            code=data["code"],
            client_id=data["client_id"],
            code_challenge=data["code_challenge"],
            redirect_uri=AnyUrl(data["redirect_uri"]),
            redirect_uri_provided_explicitly=bool(data["redirect_uri_provided_explicitly"]),
            scopes=scopes,
            expires_at=data["expires_at"],
            resource=data["resource"],
        )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        """Exchange an MCP authorization code for tokens.

        The access_token is the user's existing api_key.
        """
        # Get the api_key from the stored auth code
        data = await self.db.get_authorization_code(authorization_code.code)
        if not data:
            raise ValueError("Authorization code not found")

        api_key = data["api_key"]

        # Delete the code (single-use)
        await self.db.delete_authorization_code(authorization_code.code)

        # Generate a refresh token
        if not client.client_id:
            raise ValueError("client_id is required")
        refresh_token = secrets.token_urlsafe(32)
        await self.db.save_oauth_token(
            token=refresh_token,
            token_type="refresh",
            client_id=client.client_id,
            api_key=api_key,
            scopes=authorization_code.scopes,
            resource=authorization_code.resource,
            expires_at=None,
        )

        return OAuthToken(
            access_token=api_key,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL,
            refresh_token=refresh_token,
            scope=" ".join(authorization_code.scopes) if authorization_code.scopes else None,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        """Validate an access token (which is the user's api_key)."""
        user = await self.db.get_user_by_api_key(token)
        if not user:
            return None
        return AccessToken(
            token=token,
            client_id="",
            scopes=["claudeai"],
        )

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        """Load a refresh token."""
        data = await self.db.get_oauth_token(refresh_token)
        if not data:
            return None
        if data["token_type"] != "refresh":
            return None
        if data["client_id"] != client.client_id:
            return None

        scopes = json.loads(data["scopes"]) if data["scopes"] else []
        return RefreshToken(
            token=data["token"],
            client_id=data["client_id"],
            scopes=scopes,
            expires_at=data["expires_at"],
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Exchange a refresh token for new tokens."""
        # Get the api_key from the old refresh token
        data = await self.db.get_oauth_token(refresh_token.token)
        if not data:
            raise ValueError("Refresh token not found")

        api_key = data["api_key"]

        # Revoke the old refresh token
        await self.db.revoke_oauth_token(refresh_token.token)

        # Generate a new refresh token
        if not client.client_id:
            raise ValueError("client_id is required")
        new_refresh = secrets.token_urlsafe(32)
        await self.db.save_oauth_token(
            token=new_refresh,
            token_type="refresh",
            client_id=client.client_id,
            api_key=api_key,
            scopes=scopes or refresh_token.scopes,
            resource=None,
            expires_at=None,
        )

        return OAuthToken(
            access_token=api_key,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL,
            refresh_token=new_refresh,
            scope=" ".join(scopes) if scopes else None,
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Revoke a token."""
        if isinstance(token, RefreshToken):
            await self.db.revoke_oauth_token(token.token)
        elif isinstance(token, AccessToken):
            # Revoking an access token (api_key) = revoke all refresh tokens for this client
            await self.db.revoke_oauth_tokens_for_client(token.token, token.client_id)
