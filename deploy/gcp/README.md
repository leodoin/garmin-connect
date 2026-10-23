# GCP deployment templates

The existing service runs Python from `/opt/garmin-mcp`, saves its Garmin session under `/var/lib/garmin-mcp/garmin`, and reads its runtime key through systemd credentials from `/etc/garmin-mcp/runtime-key`. No public MCP port is needed. SSH should be restricted to IAP. The runtime needs no Google service account.

`bootstrap.sh` installs a new host from a source archive. It does not provision GCP resources or transfer secrets. Replace the tunnel ID placeholder in a private configuration before starting the service. Never overwrite an existing live configuration with the placeholder template.

For updates, test the reviewed commit, back up the existing application, and deploy application source without changing `/etc/garmin-mcp` or `/var/lib/garmin-mcp`. If dependencies change, regenerate the hashed requirements from `uv.lock` and install them in the production virtual environment. Restart `garmin-mcp.service`, check `http://127.0.0.1:8080/readyz` on the host, and run a live read. Restore the prior source/dependencies and restart if verification fails.

After schema changes, click **Refresh tools** in ChatGPT's Personal Garmin History settings and test from ChatGPT. Check returned data availability separately from request success.

No automatic production deployment is configured. Do not put production secrets into GitHub Actions or Codex Cloud merely to run tests.
