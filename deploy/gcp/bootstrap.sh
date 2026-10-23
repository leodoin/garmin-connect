#!/usr/bin/env bash
set -euo pipefail
umask 022
export DEBIAN_FRONTEND=noninteractive
if [[ "$EUID" != 0 ]]; then echo 'Run this installer with sudo.' >&2; exit 1; fi
archive="${1:?Pass the source archive path}"
install -d -m 0755 /opt/garmin-mcp /etc/garmin-mcp
apt-get update -qq
apt-get install -y -qq --no-install-recommends python3 python3-venv ca-certificates curl unzip
if ! id garmin-mcp >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/garmin-mcp --shell /usr/sbin/nologin garmin-mcp
fi
install -d -o garmin-mcp -g garmin-mcp -m 0700 /var/lib/garmin-mcp/garmin
if ! swapon --show=NAME --noheadings | grep -q .; then
  fallocate -l 1G /swapfile
  chmod 0600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
tar -xzf "$archive" -C /opt/garmin-mcp
python3 -m venv /opt/garmin-mcp/.venv
/opt/garmin-mcp/.venv/bin/pip install --no-cache-dir --require-hashes -r /opt/garmin-mcp/deploy/gcp/requirements.txt
/opt/garmin-mcp/.venv/bin/pip install --no-cache-dir --no-deps -e /opt/garmin-mcp
install -d -m 0755 /opt/garmin-mcp/bin
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
curl -fsSL --retry 3 https://api.github.com/repos/openai/tunnel-client/releases/latest -o "$stage/release.json"
python3 - "$stage" <<'PY'
import hashlib,json,pathlib,subprocess,sys,zipfile
stage=pathlib.Path(sys.argv[1])
release=json.loads((stage/'release.json').read_text())
assets={a['name']:a['browser_download_url'] for a in release['assets']}
def download(name):
 p=stage/name
 subprocess.run(['curl','-fsSL','--retry','3',assets[name],'-o',str(p)],check=True)
 return p
checksums=download('SHA256SUMS.txt').read_text().splitlines()
for prefix in ['tunnel-client-v','tunnel-client-runtime-v']:
 name=next(n for n in assets if n.startswith(prefix) and n.endswith('-linux-amd64.zip'))
 p=download(name)
 digest=hashlib.sha256(p.read_bytes()).hexdigest()
 assert any(line.split()[0]==digest and line.split()[-1].lstrip('*')==name for line in checksums)
 with zipfile.ZipFile(p) as z:
  for entry in z.infolist():
   base=pathlib.Path(entry.filename).name
   if base in ['tunnel-client','tunnel-client-runtime']:
    dest=pathlib.Path('/opt/garmin-mcp/bin')/base
    dest.write_bytes(z.read(entry));dest.chmod(0o755)
print('Official OpenAI tunnel binaries checksum-verified:',release['tag_name'])
PY
install -m 0644 /opt/garmin-mcp/deploy/gcp/tunnel.yaml /etc/garmin-mcp/tunnel.yaml
install -m 0644 /opt/garmin-mcp/deploy/gcp/garmin-mcp.service /etc/systemd/system/garmin-mcp.service
systemctl daemon-reload
echo 'Garmin software installed. Service awaits the protected Garmin session and runtime key.'
