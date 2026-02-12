import logging
from urllib.parse import urlencode

import httpx
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from strava_mcp.config import StravaSettings
from strava_mcp.db import UserDB

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
SCOPES = "read_all,activity:read,activity:read_all,profile:read_all"


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
        """Handle the OAuth callback from Strava."""
        code = request.query_params.get("code")
        error = request.query_params.get("error")

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

        # Exchange code for tokens
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
