# Personal Garmin History MCP

A single-owner, read-only MCP server for asking ChatGPT about your Garmin history. Python 3.12+; supports private stdio and a public Streamable HTTP endpoint `/mcp`. The Garmin tools make no OpenAI model API calls.

## Cloud development and the running service

The personal instance runs on a Google Cloud VM using `deploy/gcp/garmin-mcp.service` and an outbound OpenAI private tunnel. The Mac is not required. This repository contains source and deployment templates only; Garmin sessions, runtime keys, cloud credentials, and health records must never be committed.

For development from iPhone, connect this repository to a Codex Cloud environment on web/desktop, run `bash scripts/cloud-setup.sh` during setup, test with `uv run --frozen --extra dev pytest -q`, and publish the environment. Then select that environment in Codex in the ChatGPT mobile app. Development tests use mock data and require no Garmin or GCP credentials.

Changes committed to GitHub do not automatically deploy to the running VM. Review changes and tests before deploying. After tool descriptions or input schemas change, use **Refresh tools** in the Personal Garmin History settings in ChatGPT, then verify with actual tool calls. Server-side tests alone do not verify ChatGPT's cached schema.

See [cloud development](docs/cloud-development.md) and [GCP deployment](deploy/gcp/README.md).

## Run privately on a Mac

For local use, the server also supports stdio through OpenAI Secure MCP Tunnel. This keeps the MCP server off the public internet and does not require Google OAuth. The tunnel client requires a separate OpenAI runtime API key with Tunnels Read + Use; no model/API inference key is needed by the Garmin tools themselves.

The local installation has the official tunnel client and runtime in `.data/bin`, downloaded from the official release and verified against its SHA-256 checksums. Start the credential setup page with:

```sh
uv run garmin-setup
```

Open `http://127.0.0.1:8766`. Complete Garmin login/MFA there, then enter your private tunnel ID and OpenAI runtime key. The setup page is loopback-only and validates Host, Origin, session cookie, and CSRF token. The runtime key is handed to the managed tunnel process through its environment, not written into the profile or command arguments. The Garmin session is saved in `.data/garmin` with owner-only permissions. The OpenAI client stores managed-runtime metadata in macOS Application Support.

In ChatGPT, add a custom MCP server with Connection **Tunnel**, select the same tunnel, and use **No authentication** for the private stdio transport. Access is controlled by the tunnel's Platform organization and ChatGPT workspace associations. Only associate your own intended workspace. Keep the Mac awake and the tunnel running.

The three read-only tools run as `.venv/bin/python -m garmin_mcp.local`, launched by the official tunnel supervisor. There is no MCP TCP listener in this mode. The separate local setup page handles credential entry only. Check or stop the managed runtime:

```sh
.data/bin/tunnel-client runtimes status personal-garmin --json
.data/bin/tunnel-client runtimes stop personal-garmin
```

After a reboot or a stopped tunnel, reopen the local setup page and enter the runtime key again. Automatic login startup is not installed. The public HTTPS/Google OAuth alternative below is optional for a different deployment.

Tools:
- `list_activities`: page all historical workouts, newest first (up to 100 per call). Continue with `next_offset` until null. Coordinates are omitted from the list.
- `get_activity`: full workout summary by activity ID; may include location details.
- `get_health_history`: daily summary, sleep, heart rate, stress, HRV, VO₂ max, training load, load focus, training readiness, weight, body composition, or fitness age for an inclusive window of up to 31 days. Split longer history into windows. Missing measurements are not zero.

This queries Garmin on demand; it does not yet maintain a local historical database. Old data availability depends on your account and device. Large heart-rate responses are best requested one day at a time. Garmin access uses the unofficial `garminconnect` library, not Garmin's official partner API; service changes may require updates. Only read methods are exposed, though the underlying Garmin session has broader account privileges.

## Install and log in locally

Run from this repository:

```sh
uv sync --extra dev
cp .env.example .env
uv run garmin-login
```

Enter your Garmin email, password, and MFA in the terminal prompts. Do not put these in chat, source code, or GitHub. The saved session lives in `.data/garmin`, ignored by Git. Treat it as a password. No Garmin credentials are sent to ChatGPT.

## Google sign-in for ChatGPT access

Garmin login and MCP login are separate: the server holds your Garmin session; Google OAuth permits only your configured Google identity to read it.

1. Choose a stable HTTPS origin for the server, e.g. `https://garmin.example.com`. A development HTTPS tunnel to local port 8000 also works; keep your Mac awake. Use a TLS reverse proxy for hosting; do not expose port 8000 directly to the internet.
2. In Google Cloud Console, configure an OAuth consent screen and a **Web application** OAuth client. For personal testing, add your Google account as a test user. Add `https://garmin.example.com/auth/callback` as the exact authorized redirect URI. Replace the origin with your real one.
3. Fill `.env`: `MCP_BASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `ALLOWED_GOOGLE_EMAIL`. The allowed email is your Google sign-in identity and can differ from your Garmin email.
4. Generate `MCP_SIGNING_KEY` using the command in `.env.example`. Keep it private and stable. Protect `.env` with `chmod 600 .env`.
5. Start `uv run garmin-mcp`. There is deliberately no unauthenticated public startup mode. The server requires HTTPS origin configuration and rejects other Google identities and unverified email addresses.

FastMCP handles OAuth discovery, registration, PKCE, and consent. OAuth state is stored by the pinned FastMCP release in an encrypted disk store under `.data/mcp`. Preserve this directory and the signing key across restarts; back them up securely. Run one server process against this local store. Google test-mode refresh-token limits may also require reconnecting.

## Connect ChatGPT

In ChatGPT's web settings, enable developer mode where available for your plan/workspace, then create a custom app/MCP connection:

- URL: `https://YOUR-ORIGIN/mcp`
- Authentication: OAuth
- Complete Google sign-in with `ALLOWED_GOOGLE_EMAIL`, approve consent, and scan tools.

Availability and UI vary by ChatGPT plan/workspace. A plain localhost URL is not reachable from ChatGPT. Use your HTTPS server or a supported private MCP tunnel. Do not select “No authentication” for a public personal-health endpoint.

Try: “List my last 50 runs,” “Compare my sleep and HRV for the first two weeks of September,” or “Page through my workouts until January 2023 and summarize my running volume.” Historical pagination is explicit so the model must continue requesting pages; a single page is not your entire history.

## Development

```sh
uv run pytest
```

Tests use fake Garmin responses and an in-process MCP client. They cover date bounds, pagination, coordinate omission, safe errors, missing login, tool registration/calls, and rejection of other Google identities. Live Garmin login and ChatGPT OAuth need your accounts and are not covered by mocked tests.

Sources: [OpenAI MCP server guide](https://developers.openai.com/plugins/build/mcp-server), [OpenAI authentication guide](https://developers.openai.com/plugins/build/auth), [Garmin client](https://github.com/cyberjunky/python-garminconnect), [FastMCP Google provider](https://github.com/PrefectHQ/fastmcp/blob/main/src/fastmcp/server/auth/providers/google.py).
