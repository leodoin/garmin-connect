# GCP deployment templates

The existing service runs Python from `/opt/garmin-mcp`, saves its Garmin session under `/var/lib/garmin-mcp/garmin`, and reads its runtime key through systemd credentials from `/etc/garmin-mcp/runtime-key`. No public MCP port is needed. SSH should be restricted to IAP. The runtime needs no Google service account.

`bootstrap.sh` installs a new host from a source archive. It does not provision GCP resources or transfer secrets. Replace the tunnel ID placeholder in a private configuration before starting the service. Never overwrite an existing live configuration with the placeholder template.

For updates, test the reviewed commit, back up the existing application, and deploy application source without changing `/etc/garmin-mcp` or `/var/lib/garmin-mcp`. If dependencies change, regenerate the hashed requirements from `uv.lock` and install them in the production virtual environment. Restart `garmin-mcp.service`, check `http://127.0.0.1:8080/readyz` on the host, and run a live read. Restore the prior source/dependencies and restart if verification fails.

After schema changes, click **Refresh tools** in ChatGPT's Personal Garmin History settings and test from ChatGPT. Check returned data availability separately from request success.

## Deploy from GitHub

Open Actions → **Deploy to GCP** → **Run workflow** → choose `main` → **Run workflow**. The workflow deploys the exact main-branch commit captured when the run starts. Pushes and pull requests run tests without deploying. Use the Actions deployment from the GitHub mobile app or mobile browser when working from iPhone.

The job tests first, then uses GitHub OIDC and Google Workload Identity Federation to impersonate a dedicated deployment service account. Trust is restricted to this repository's numeric owner/repository IDs, main branch, this workflow path, and manual workflow dispatch. Google access is restricted to SSH metadata on the existing VM, project lookup/operation polling, and IAP SSH to its internal address. No long-lived GCP key is stored in GitHub. The GitHub production environment accepts main-branch deployments only.

The VM downloads the immutable public GitHub commit archive over HTTPS and verifies the SHA-256 recorded by the runner. IAP carries only the deployment command. This avoids large SCP uploads through IAP.

A fresh release and virtual environment are staged under `/opt/garmin-releases`. The prior release is preserved. The job switches `/opt/garmin-mcp` only after package validation, restarts the service, checks tunnel readiness and a live Garmin read, and rolls back on verification failure. A brief interruption occurs during restart. `/etc/garmin-mcp` and `/var/lib/garmin-mcp` are preserved, including the private tunnel key, live configuration, and Garmin session. Review disk usage periodically; old releases are retained for rollback.

GitHub permission to change main and manually run this workflow grants production deployment access. Production software can access the saved Garmin session by design, so deploy reviewed code only. Never accept untrusted pull-request code into main without review. No deployment is triggered by `pull_request_target`.

To roll back manually in the VM's SSH terminal, stop the service, point `/opt/garmin-mcp` back to the previous release path printed by the workflow, restart, and check `/readyz`. The initial prior installation is retained as a `legacy-*` release. Never delete session/key directories to roll back source code.

Do not put production secrets into GitHub Actions or Codex Cloud merely to run tests.
