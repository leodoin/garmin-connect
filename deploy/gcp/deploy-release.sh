#!/usr/bin/env bash
# Run as root on the existing VM: deploy-release.sh ARCHIVE COMMIT_SHA
set -euo pipefail
umask 022
archive="${1:?Source archive required}"
revision="${2:?Commit SHA required}"
[[ "$EUID" == 0 && "$revision" =~ ^[0-9a-f]{40}$ ]] || exit 2
exec 9>/var/lock/garmin-mcp-deploy.lock
flock -n 9 || { echo 'Another deployment is running'; exit 1; }
app=/opt/garmin-mcp
releases=/opt/garmin-releases
release="$releases/$revision-$(date -u +%Y%m%dT%H%M%SZ)"
[[ -f /etc/garmin-mcp/runtime-key && -f /etc/garmin-mcp/tunnel.yaml ]]
[[ ! -e "$release" ]] || { echo 'This release already exists; use a new commit or inspect the prior attempt.'; exit 1; }
mkdir -p "$release"
tar -xzf "$archive" --strip-components=1 -C "$release"
python3 -m venv "$release/.venv"
"$release/.venv/bin/pip" install --no-compile --no-cache-dir --require-hashes -r "$release/deploy/gcp/requirements.txt"
"$release/.venv/bin/pip" install --no-compile --no-cache-dir --no-deps "$release"
cp -a "$app/bin" "$release/bin"
printf '%s\n' "$revision" > "$release/REVISION"
# Validate the installed MCP package as the service user before touching production.
(cd "$release" && sudo -u garmin-mcp "$release/.venv/bin/python" - <<'PY'
import asyncio
from fastmcp import Client
from garmin_mcp.history import History
from garmin_mcp.server import create_server
async def main():
    async with Client(create_server(History('/var/lib/garmin-mcp/garmin'))) as client:
        tools = await client.list_tools()
        assert {t.name for t in tools} >= {'list_activities','get_activity','get_health_history'}
asyncio.run(main())
PY
)
if [[ -L "$app" ]]; then
  previous=$(readlink -f "$app")
else
  previous="$releases/legacy-$(date -u +%Y%m%dT%H%M%SZ)"
fi
switched=false
rollback() {
  code=$?
  trap - ERR
  if [[ "$switched" == true ]]; then
    echo 'Verification failed; restoring previous release.' >&2
    systemctl stop garmin-mcp.service || true
    ln -s "$previous" "$app.rollback"
    mv -Tf "$app.rollback" "$app"
    systemctl start garmin-mcp.service || true
  fi
  exit "$code"
}
trap rollback ERR
systemctl stop garmin-mcp.service
if [[ ! -L "$app" ]]; then
  mv "$app" "$previous"
fi
switched=true
ln -s "$release" "$app.next"
mv -Tf "$app.next" "$app"
systemctl start garmin-mcp.service
ready=false
for attempt in $(seq 1 45); do
  if curl -fsS http://127.0.0.1:8080/readyz >/dev/null; then ready=true; break; fi
  sleep 2
done
[[ "$ready" == true ]]
systemctl is-active --quiet garmin-mcp.service
# A real Garmin read catches missing credentials/connectivity; never print personal data.
(cd "$app" && sudo -u garmin-mcp "$release/.venv/bin/python" - <<'PY'
from garmin_mcp.history import History
result = History('/var/lib/garmin-mcp/garmin').activities(limit=1)
assert isinstance(result['activities'], list)
print('Live Garmin read succeeded; personal data omitted.')
PY
)
trap - ERR
printf 'Deployed commit %s; previous release: %s\n' "$revision" "$previous"
echo 'If MCP schemas changed, refresh tools in ChatGPT and verify a live tool call.'
