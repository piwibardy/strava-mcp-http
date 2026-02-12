# Strava MCP Server

[![CI/CD Pipeline](https://github.com/piwibardy/strava-mcp-http/actions/workflows/ci.yml/badge.svg)](https://github.com/piwibardy/strava-mcp-http/actions/workflows/ci.yml)

A Model Context Protocol (MCP) server for interacting with the Strava API. Supports both **stdio** and **streamable-http** transports, multi-tenant authentication, and MCP OAuth 2.0 for Claude Desktop custom connectors.

## User Guide

### Installation

You can install Strava MCP with `uvx`:

```bash
uvx strava-mcp
```

### Docker

Build and run the server with Docker (defaults to streamable-http on port 8000):

```bash
docker build -t strava-mcp .
docker run -p 8000:8000 \
  -e STRAVA_CLIENT_ID=your_client_id \
  -e STRAVA_CLIENT_SECRET=your_client_secret \
  -e SERVER_BASE_URL=https://your-public-url.com \
  strava-mcp
```

A pre-built image is also available on GHCR:

```bash
docker pull ghcr.io/piwibardy/strava-mcp-http:latest
```

### Setting Up Strava Credentials

1. **Create a Strava API Application**:
   - Go to [https://www.strava.com/settings/api](https://www.strava.com/settings/api)
   - Create a new application to obtain your Client ID and Client Secret
   - For "Authorization Callback Domain", enter your server's domain (e.g. `localhost` for local dev, or your tunnel/production domain)

2. **Configure Your Credentials**:
   Create a `.env` file or export environment variables:

   ```bash
   STRAVA_CLIENT_ID=your_client_id
   STRAVA_CLIENT_SECRET=your_client_secret
   ```

### Connecting to Claude Desktop

There are two ways to connect this server to Claude Desktop:

#### Option 1: Custom Connector (MCP OAuth — recommended)

This uses the native MCP OAuth 2.0 flow. Requires HTTPS (e.g. via a Cloudflare tunnel or production deployment).

1. Start the server with `SERVER_BASE_URL` pointing to your public HTTPS URL
2. In Claude Desktop, add a **custom connector** with URL: `https://your-server.com/mcp`
3. Claude Desktop will handle the full OAuth flow automatically (register → authorize → Strava → callback → token)

#### Option 2: stdio via mcp-remote

Use `mcp-remote` to bridge stdio and HTTP transport:

```json
{
  "strava": {
    "command": "npx",
    "args": [
      "mcp-remote",
      "http://localhost:8000/mcp",
      "--header",
      "Authorization: Bearer YOUR_API_KEY"
    ]
  }
}
```

To get your API key, visit `http://localhost:8000/auth/strava` and complete the Strava OAuth flow.

#### Option 3: stdio (single-user)

```json
{
  "strava": {
    "command": "bash",
    "args": [
      "-c",
      "source ~/.ssh/strava.sh && uvx strava-mcp"
    ]
  }
}
```

### Authentication

The server supports multiple authentication modes:

- **MCP OAuth 2.0**: Used by Claude Desktop custom connectors. The server acts as an OAuth authorization server, delegating to Strava for user authentication. Fully automatic.
- **Bearer API key**: For HTTP transport with `mcp-remote` or direct API access. Get your key by visiting `/auth/strava`.
- **stdio (single-user)**: Uses `STRAVA_REFRESH_TOKEN` environment variable directly.

### Available Tools

#### get_user_activities
Retrieves activities for the authenticated user.

**Parameters:**
- `before` (optional): Epoch timestamp for filtering
- `after` (optional): Epoch timestamp for filtering
- `page` (optional): Page number (default: 1)
- `per_page` (optional): Number of items per page (default: 30)

#### get_activity
Gets detailed information about a specific activity.

**Parameters:**
- `activity_id`: The ID of the activity
- `include_all_efforts` (optional): Include segment efforts (default: false)

#### get_activity_segments
Retrieves segments from a specific activity.

**Parameters:**
- `activity_id`: The ID of the activity

#### get_rate_limit_status
Returns the current Strava API rate limit status from the most recent API call. Use this to check remaining quota before making multiple requests.

**Returns:**
```json
{
  "short_term": { "usage": 45, "limit": 100, "remaining": 55 },
  "daily": { "usage": 320, "limit": 1000, "remaining": 680 }
}
```

Strava enforces rate limits of 100 requests/15 min and 1,000 requests/day for read operations. The server automatically retries once on 429 responses after waiting for the next 15-minute window.

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `STRAVA_CLIENT_ID` | Yes | — | Strava API client ID |
| `STRAVA_CLIENT_SECRET` | Yes | — | Strava API client secret |
| `SERVER_BASE_URL` | No | `http://localhost:8000` | Public base URL (for OAuth redirects) |
| `STRAVA_REFRESH_TOKEN` | No | — | Refresh token (single-user stdio mode) |
| `STRAVA_DATABASE_PATH` | No | `data/users.db` | SQLite database path |

## Developer Guide

### Project Setup

1. Clone the repository:
   ```bash
   git clone git@github.com:piwibardy/strava-mcp-http.git
   cd strava-mcp-http
   ```

2. Install dependencies:
   ```bash
   uv sync
   ```

3. Set up environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with your Strava credentials
   ```

### Running in Development Mode

Run the server with MCP CLI:
```bash
mcp dev strava_mcp/main.py
```

Or with HTTP transport:
```bash
uv run strava-mcp --transport streamable-http --port 8000
```

For HTTPS in development, use a Cloudflare tunnel:
```bash
cloudflared tunnel --url http://localhost:8000
```

### Project Structure

- `strava_mcp/`: Main package directory
  - `config.py`: Configuration settings using pydantic-settings
  - `models.py`: Pydantic models for Strava API entities
  - `api.py`: Low-level API client for Strava (with rate limit tracking)
  - `auth.py`: Strava OAuth callback routes (supports both MCP OAuth and legacy flows)
  - `oauth_provider.py`: MCP OAuth 2.0 Authorization Server provider
  - `middleware.py`: Bearer auth middleware (legacy compatibility)
  - `db.py`: Async SQLite store for users, OAuth clients, tokens
  - `service.py`: Service layer for business logic
  - `server.py`: MCP server implementation and tool definitions
  - `main.py`: Main entry point (argparse for transport/host/port)
- `tests/`: Unit tests
- `Dockerfile`: Multi-stage Docker build

### Running Tests

```bash
uv run pytest
```

### Linting

```bash
uv run ruff check . && uv run ruff format --check .
```

## License

[MIT License](LICENSE)

## Acknowledgements

- [Strava API](https://developers.strava.com/)
- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
- Forked from [yorrickjansen/strava-mcp](https://github.com/yorrickjansen/strava-mcp)
