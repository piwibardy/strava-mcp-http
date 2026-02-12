# Strava MCP Server

[![CI/CD Pipeline](https://github.com/piwibardy/strava-mcp-http/actions/workflows/ci.yml/badge.svg)](https://github.com/piwibardy/strava-mcp-http/actions/workflows/ci.yml)

A Model Context Protocol (MCP) server for interacting with the Strava API. Supports both **stdio** and **streamable-http** transports.

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
  strava-mcp
```

### Setting Up Strava Credentials

1. **Create a Strava API Application**:
   - Go to [https://www.strava.com/settings/api](https://www.strava.com/settings/api)
   - Create a new application to obtain your Client ID and Client Secret
   - For "Authorization Callback Domain", enter `localhost`

2. **Configure Your Credentials**:
   Create a credentials file (e.g., `~/.ssh/strava.sh`):

   ```bash
   export STRAVA_CLIENT_ID=your_client_id
   export STRAVA_CLIENT_SECRET=your_client_secret
   ```

3. **Configure Claude Desktop** (stdio transport):
   Add the following to your Claude configuration (`/Users/<username>/Library/Application Support/Claude/claude_desktop_config.json`):

   ```json
   "strava": {
       "command": "bash",
       "args": [
           "-c",
           "source ~/.ssh/strava.sh && uvx strava-mcp"
       ]
   }
   ```

4. **HTTP transport** (e.g. for remote or Docker deployments):

   ```bash
   strava-mcp --transport streamable-http --host 0.0.0.0 --port 8000
   ```

### Authentication

The first time you use the Strava MCP tools:

1. An authentication flow will automatically start
2. Your browser will open to the Strava authorization page
3. After authorizing, you'll be redirected back to a local page
4. Your refresh token will be saved automatically for future use

### Available Tools

#### Get User Activities
Retrieves activities for the authenticated user.

**Parameters:**
- `before` (optional): Epoch timestamp for filtering
- `after` (optional): Epoch timestamp for filtering
- `page` (optional): Page number (default: 1)
- `per_page` (optional): Number of items per page (default: 30)

#### Get Activity
Gets detailed information about a specific activity.

**Parameters:**
- `activity_id`: The ID of the activity
- `include_all_efforts` (optional): Include segment efforts (default: false)

#### Get Activity Segments
Retrieves segments from a specific activity.

**Parameters:**
- `activity_id`: The ID of the activity

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
   export STRAVA_CLIENT_ID=your_client_id
   export STRAVA_CLIENT_SECRET=your_client_secret
   ```
   Alternatively, create a `.env` file with these variables.

### Running in Development Mode

Run the server with MCP CLI:
```bash
mcp dev strava_mcp/main.py
```

Or with HTTP transport:
```bash
uv run strava-mcp --transport streamable-http --port 8000
```

### Manual Authentication

You can get a refresh token manually by running:
```bash
python get_token.py
```

### Project Structure

- `strava_mcp/`: Main package directory
  - `__init__.py`: Package initialization
  - `config.py`: Configuration settings using pydantic-settings
  - `models.py`: Pydantic models for Strava API entities
  - `api.py`: Low-level API client for Strava
  - `auth.py`: Strava OAuth authentication implementation
  - `oauth_server.py`: Standalone OAuth server implementation
  - `service.py`: Service layer for business logic
  - `server.py`: MCP server implementation
  - `main.py`: Main entry point (argparse for transport/host/port)
- `tests/`: Unit tests
- `Dockerfile`: Multi-stage Docker build
- `get_token.py`: Utility script to get a refresh token manually

### Running Tests

```bash
pytest
```

### Publishing to PyPI

#### Building the package
```bash
uv build
```

#### Publishing to PyPI
```bash
# Publish to Test PyPI first
uv publish --index testpypi

# Publish to PyPI
uv publish
```

## License

[MIT License](LICENSE)

## Acknowledgements

- [Strava API](https://developers.strava.com/)
- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
- Forked from [yorrickjansen/strava-mcp](https://github.com/yorrickjansen/strava-mcp)
