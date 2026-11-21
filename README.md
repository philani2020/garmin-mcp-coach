# garmin-mcp-coach

An MCP server that gives an AI assistant read-only access to your own Garmin Connect data
(sleep, HRV, Body Battery, stress, activities and more) through the Garmin Connect Personal API.
Use it with Claude (Desktop or Code) or ChatGPT to ask coaching questions about your training
and recovery.

```
  Claude Desktop / Claude Code ── stdio ──┐
                                          ▼
                                   garmin-mcp server ──► Garmin Connect Personal API
                                          ▲
  ChatGPT ── HTTPS ── tunnel ── HTTP ─────┘
```

## Install

Needs Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/<your-username>/garmin-mcp-coach.git
cd garmin-mcp-coach
uv sync
cp .env.example .env      # paste GARMIN_PERSONAL_API_KEY
```

Get a key at https://connect.garmin.com/app/settings/personalApiToken. It's shown once and
expires after 30, 90, 180 or 365 days. The server loads `.env` from the project folder, so the
key doesn't need to go into any client config.

Test with the inspector: `npx @modelcontextprotocol/inspector uv run garmin-mcp`

> If you use this folder from both Windows and WSL, `.venv` can only belong to one of them. Set
> `UV_PROJECT_ENVIRONMENT=~/.venvs/garmin-mcp-coach` on the WSL side, or uv will rebuild `.venv`
> for Linux and break the Windows clients.

## Use with Claude

Claude runs the server locally over stdio. In the examples below, replace
`/path/to/garmin-mcp-coach` with the absolute path where you cloned the repo (on Windows,
something like `C:\\Users\\you\\garmin-mcp-coach` in JSON).

**Claude Desktop** (`%APPDATA%\Claude\claude_desktop_config.json` on Windows,
`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "garmin": {
      "command": "uv",
      "args": ["--directory", "/path/to/garmin-mcp-coach", "run", "garmin-mcp"]
    }
  }
}
```

**Claude Code:**

```bash
claude mcp add garmin -- uv --directory /path/to/garmin-mcp-coach run garmin-mcp
```

## Use with ChatGPT

ChatGPT can't start a local process, so it can't use stdio. It connects to MCP servers over
HTTPS from OpenAI's servers. To use this server you run it in HTTP mode and give it a public
HTTPS URL, usually with a tunnel.

### 1. Run the server in HTTP mode

Add to `.env`:

```bash
GARMIN_MCP_TRANSPORT=streamable-http
GARMIN_MCP_PORT=8000
# Pick your own random string. Anyone who knows the full URL can read your Garmin data.
GARMIN_MCP_PATH=/mcp-3f9c1e7a2b8d4c60a5e1
```

Generate a random path with `python -c "import secrets; print('/mcp-' + secrets.token_hex(16))"`.

Start it:

```bash
uv run garmin-mcp
```

It listens on `http://127.0.0.1:8000/mcp-<random>`. Leave `GARMIN_MCP_HOST` at `127.0.0.1`
so only the tunnel can reach it.

### 2. Expose it over HTTPS

Use either tunnel. Both need the Host header rewritten to `localhost`: the server only accepts
requests addressed to localhost (DNS-rebinding protection) and rejects others with
`421 Invalid Host header`.

**Cloudflare Tunnel** (free, no account needed for a quick tunnel):

```bash
cloudflared tunnel --url http://localhost:8000 --http-host-header localhost:8000
```

**ngrok:**

```bash
ngrok http 8000 --host-header=rewrite
```

Each prints a public URL such as `https://random-words.trycloudflare.com`. Your MCP server URL is
that address plus your path:

```
https://random-words.trycloudflare.com/mcp-3f9c1e7a2b8d4c60a5e1
```

Quick tunnels get a new URL every time they start. For a stable URL, use a named Cloudflare
Tunnel or an ngrok static domain, and update the connector in ChatGPT if the URL changes.

### 3. Add the connector in ChatGPT

Custom MCP connectors need a ChatGPT plan that supports developer mode (Plus, Pro, Business,
Enterprise or Edu; on workspace plans an admin may have to allow it). The menu names below may
differ slightly as OpenAI changes the UI.

1. In ChatGPT, open **Settings → Apps & Connectors → Advanced settings** and turn on
   **Developer mode**.
2. Back in **Apps & Connectors**, click **Create** (or **Add custom connector**).
3. Fill in:
   - **Name:** `Garmin`
   - **Description:** `Read-only access to my Garmin Connect health and training data`
   - **MCP Server URL:** your full tunnel URL including the path
   - **Authentication:** `No authentication` (the random path is the only protection; see below)
4. Tick that you trust the connector and click **Create**. ChatGPT lists the tools it found.
   If it reports an error, check the server and tunnel logs.
5. In a new chat, open the **+** menu, choose **Developer mode** and enable the **Garmin**
   connector. Then ask something like:

   > Look at my last 14 days of sleep, HRV and Body Battery along with my runs. Am I recovering
   > well enough to do intervals tomorrow?

ChatGPT asks before running tools it doesn't know. All the tools except
`download_activity_file` are marked read-only. That one saves a file on the machine running the
server, not in ChatGPT, so it's of little use from ChatGPT.

### Security

The HTTP transport has **no authentication**. Anyone who has the full URL can read your health
data through your API key. To keep that risk small:

- Keep `GARMIN_MCP_PATH` long and random, and don't share the URL. Change it if it leaks.
- Bind to `127.0.0.1` (the default) and expose the server only through the tunnel.
- Stop the tunnel when you're not using ChatGPT.
- Give the Garmin API key the shortest expiry that suits you, and revoke it at
  https://connect.garmin.com/app/settings/personalApiToken if needed.

The tunnel URL appears in your ChatGPT connector settings, and OpenAI's servers send the
requests. If you need real access control, put the server behind an OAuth-capable gateway and
pick OAuth as the connector's authentication.

## How auth to Garmin works

1. The server reads your Personal API key from `GARMIN_PERSONAL_API_KEY`.
2. On first use it POSTs the key to
   `https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token`
   with `Authorization: ApiKey <key>` and gets back a JWT.
3. It keeps the JWT in memory and sends it as `Authorization: Bearer <jwt>`. Tokens live 24h and
   there are no refresh tokens, so it mints a new one when less than 1h remains, and once more
   on any 401.

The server never writes the key to disk.

## Tools

All dates are `YYYY-MM-DD` (or `today`); ranges are inclusive.

| Area | Tools |
|---|---|
| Profile | `get_user_profile_settings`, `get_heart_rate_zones` |
| Daily | `get_daily_summaries`, `get_daily_steps`, `get_daily_stress`, `get_daily_hydration`, `get_body_battery`, `get_wellness_activity_summaries` |
| Sleep | `get_sleep`, `get_sleep_summaries` |
| Heart | `get_heart_rate`, `get_hrv`, `get_hrv_summaries`, `get_spo2`, `get_fitness_age` |
| Body / nutrition | `get_weight_measurements`, `get_weight_goals`, `get_food_logs` |
| Women's health | `get_menstrual_cycle_summary`, `get_menstrual_cycle_day_view` |
| Activities | `search_activities`, `get_activity`, `get_activity_workouts`, `download_activity_file` |
| Escape hatch | `garmin_get`: raw GET for any endpoint without a dedicated tool |

`download_activity_file` saves the original ZIP/.fit to `GARMIN_DOWNLOAD_DIR` (default
`~/Downloads/garmin`) on the machine running the server.

## Environment

| Variable | Default |
|---|---|
| `GARMIN_PERSONAL_API_KEY` | **required** |
| `GARMIN_PERSONAL_API_BASE_URL` | `https://personal.connectapi.garmin.com` |
| `GARMIN_DOWNLOAD_DIR` | `~/Downloads/garmin` |
| `GARMIN_TIMEOUT_SECONDS` | `30` |
| `GARMIN_LOG_LEVEL` | `WARNING` (logs go to stderr) |
| `GARMIN_MCP_TRANSPORT` | `stdio`, or `streamable-http` for ChatGPT and other remote clients |
| `GARMIN_MCP_HOST` | `127.0.0.1` (HTTP only) |
| `GARMIN_MCP_PORT` | `8000` (HTTP only) |
| `GARMIN_MCP_PATH` | `/mcp` (HTTP only; use a long random path when exposed) |

## Layout

```
src/garmin_mcp/client.py    Garmin API client, auth and .env loading
src/garmin_mcp/server.py    MCP tools and transport setup
```
