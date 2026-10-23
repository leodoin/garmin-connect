# Personal Garmin History MCP

Python 3.12+; FastMCP, unofficial garminconnect library. Production uses private stdio through an outbound OpenAI tunnel on GCP. A protected public HTTP alternative is also supported.

## Setup and verification

- Setup: `bash scripts/cloud-setup.sh`
- Tests: `uv run --frozen --extra dev pytest -q`
- Main modules: `src/garmin_mcp/history.py` (Garmin reads), `server.py` (tool schemas/auth), `local.py` (stdio), `local_setup.py` (local credential UI).
- Existing tests must pass. Add meaningful regression coverage for behavior changes.
- Keep exposed operations read-only. Never introduce arbitrary Garmin method dispatch from tool inputs.
- Preserve bounded dates (31 days), explicit pagination, serialized session access, and sanitized errors.
- Missing measurements are unavailable, never zero. Preserve documented upstream units; weight may be grams.

## Secrets and deployment

Never read or commit live Garmin sessions, passwords, keys, health records, `.data`, `.env`, SSH credentials, or cloud SDK state. Tests use mocks; no production credentials are needed for coding.

Deployment templates are under `deploy/gcp`. Source changes do not deploy automatically. Do not change production or grant cloud access unless the user asks. Keep production configuration and state outside source control.

After changing an MCP schema, deployment must include refreshing tools in ChatGPT plugin settings and a live ChatGPT call to verify the refreshed schema. Do not claim client compatibility based only on backend tests.
