import json
import logging
import secrets
import time
from urllib.parse import urlencode

import httpx
from mcp.server.auth.provider import construct_redirect_uri
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from strava_mcp.config import StravaSettings
from strava_mcp.db import UserDB

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
SCOPES = "read_all,activity:read,activity:read_all,profile:read_all"
AUTH_CODE_TTL = 600  # 10 minutes


def get_redirect_uri(settings: StravaSettings) -> str:
    """Build the OAuth redirect URI from server settings."""
    base = settings.server_base_url.rstrip("/")
    return f"{base}/auth/callback"


def create_auth_routes(settings: StravaSettings, db: UserDB) -> list[Route]:
    """Create Starlette routes for OAuth authentication.

    Args:
        settings: Strava settings
        db: User database

    Returns:
        List of Starlette Route objects to mount on the app
    """

    async def auth_strava(request: Request) -> Response:
        """Redirect the user to Strava's OAuth authorization page."""
        params = {
            "client_id": settings.client_id,
            "redirect_uri": get_redirect_uri(settings),
            "response_type": "code",
            "approval_prompt": "force",
            "scope": SCOPES,
        }
        auth_url = f"{AUTHORIZE_URL}?{urlencode(params)}"
        logger.info("Redirecting user to Strava OAuth: %s", auth_url)
        return RedirectResponse(auth_url)

    async def auth_callback(request: Request) -> Response:
        """Handle the OAuth callback from Strava.

        Supports two flows:
        - MCP OAuth: state matches a pending session -> redirect to Claude
        - Legacy: no pending session -> show HTML page with API key
        """
        code = request.query_params.get("code")
        error = request.query_params.get("error")
        state = request.query_params.get("state")

        if error:
            logger.error("OAuth error from Strava: %s", error)
            return HTMLResponse(
                f"<h1>Authorization failed</h1><p>Strava returned error: {error}</p>",
                status_code=400,
            )

        if not code:
            return HTMLResponse(
                "<h1>Authorization failed</h1><p>No authorization code received.</p>",
                status_code=400,
            )

        # Exchange Strava code for tokens
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    TOKEN_URL,
                    data={
                        "client_id": settings.client_id,
                        "client_secret": settings.client_secret,
                        "code": code,
                        "grant_type": "authorization_code",
                    },
                )

                if resp.status_code != 200:
                    logger.error("Token exchange failed: %s", resp.text)
                    return HTMLResponse(
                        "<h1>Authorization failed</h1><p>Could not exchange authorization code.</p>",
                        status_code=500,
                    )

                data = resp.json()
                athlete_id = data["athlete"]["id"]
                access_token = data["access_token"]
                refresh_token = data["refresh_token"]
                expires_at = data["expires_at"]

            # Store user in DB (upsert: update if athlete already exists)
            api_key = await db.upsert_user(
                strava_athlete_id=athlete_id,
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=expires_at,
            )

            # Check if this is an MCP OAuth flow
            if state:
                pending = await db.get_pending_session(state)
                if pending:
                    # MCP OAuth: generate auth code, redirect to Claude
                    await db.delete_pending_session(state)

                    mcp_auth_code = secrets.token_urlsafe(32)
                    scopes = json.loads(pending["scopes"]) if pending["scopes"] else []

                    await db.save_authorization_code(
                        code=mcp_auth_code,
                        client_id=pending["client_id"],
                        api_key=api_key,
                        code_challenge=pending["code_challenge"],
                        redirect_uri=pending["redirect_uri"],
                        redirect_uri_provided_explicitly=bool(pending["redirect_uri_provided_explicitly"]),
                        scopes=scopes,
                        resource=pending["resource"],
                        expires_at=time.time() + AUTH_CODE_TTL,
                    )

                    redirect_url = construct_redirect_uri(
                        pending["redirect_uri"],
                        code=mcp_auth_code,
                        state=pending["mcp_state"],
                    )
                    logger.info("MCP OAuth: redirecting to client with auth code")
                    return RedirectResponse(redirect_url, status_code=302)

            # Legacy flow: show HTML page with API key
            athlete_name = data.get("athlete", {}).get("firstname", "Athlete")

            return HTMLResponse(f"""
                <html>
                <head><title>Strava MCP - Authorized</title></head>
                <body style="font-family: sans-serif; max-width: 600px;
                             margin: 50px auto; padding: 20px;">
                    <h1>Authorization successful!</h1>
                    <p>Welcome, <strong>{athlete_name}</strong>!</p>
                    <p>Your API key:</p>
                    <pre style="background: #f0f0f0; padding: 15px; border-radius: 5px;
                                word-break: break-all; user-select: all;">{api_key}</pre>
                    <p>Configure your MCP client with this header:</p>
                    <pre style="background: #f0f0f0; padding: 15px;
                                border-radius: 5px;">Authorization: Bearer {api_key}</pre>
                    <p style="color: #666; font-size: 0.9em;">
                        Save this key — you won't be able to see it again.<br>
                        If you lose it, re-authorize at
                        <code>/auth/strava</code> to get the same key back.
                    </p>
                </body>
                </html>
            """)

        except Exception:
            logger.exception("Error during OAuth callback")
            return HTMLResponse(
                "<h1>Authorization failed</h1><p>An unexpected error occurred.</p>",
                status_code=500,
            )

    return [
        Route("/auth/strava", auth_strava, methods=["GET"]),
        Route("/auth/callback", auth_callback, methods=["GET"]),
    ]
