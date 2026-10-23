"""Loopback-only setup. Passwords remain in memory and never enter command args."""
import json
import os
import re
import secrets
import shlex
import subprocess
import threading
from pathlib import Path

import uvicorn
from garminconnect import Garmin
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from .local import ROOT

ORIGIN = "http://127.0.0.1:8766"
DATA = ROOT / ".data"
TUNNEL = DATA / "bin/tunnel-client"
CONFIG = DATA / "local-config.json"

PAGE = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Personal Garmin · Local setup</title>
<style>body{font:16px system-ui;background:#f3f6f5;color:#12352c;max-width:680px;margin:48px auto;padding:24px}section{background:white;border:1px solid #d9e4df;border-radius:16px;padding:24px;margin:20px 0}h1{font-size:30px}label{display:block;margin:16px 0 5px}input{box-sizing:border-box;width:100%;padding:12px;border:1px solid #abc2b8;border-radius:8px;font:inherit}button{background:#126349;color:white;padding:12px 20px;border:0;border-radius:8px;font:inherit;margin-top:16px;cursor:pointer}p{line-height:1.5}.status{white-space:pre-line;color:#315b4d}small{color:#50675e}a{color:#126349}</style>
<h1>Personal Garmin</h1><p>This setup runs on your Mac. Your Garmin password and OpenAI runtime key never go through chat. Garmin session tokens are saved privately on this Mac.</p>
<section><h2>1. Connect Garmin</h2><form id="login"><label for="email">Garmin email</label><input id="email" type="email" autocomplete="username" required><label for="password">Garmin password</label><input id="password" type="password" autocomplete="current-password" required><button>Connect Garmin</button></form>
<form id="mfa" hidden><label for="code">Garmin MFA code</label><input id="code" inputmode="numeric" autocomplete="one-time-code" required><button>Verify code</button></form><p id="garminStatus" class="status">Checking…</p></section>
<section><h2>2. Connect the private OpenAI tunnel</h2><p>Create a dedicated runtime API key in <a href="https://platform.openai.com/settings/organization/api-keys" target="_blank" rel="noreferrer">OpenAI Platform</a> with Tunnels Read + Use. Enter it here; it is passed to the tunnel through its environment and is not saved to disk.</p>
<form id="tunnel"><label for="tunnelId">Tunnel ID</label><input id="tunnelId" autocomplete="off" required><label for="runtimeKey">OpenAI runtime API key</label><input id="runtimeKey" type="password" autocomplete="off" required><button>Start private tunnel</button></form><p id="tunnelStatus" class="status">Not started</p></section>
<section><h2>3. Connect ChatGPT</h2><p>Once the tunnel is ready, open <a href="https://chatgpt.com/#settings/Connectors" target="_blank" rel="noreferrer">ChatGPT app settings</a>, add a custom MCP server, choose <b>Tunnel</b>, and select Personal Garmin History. Use <b>No authentication</b> for this private tunnel: access is controlled by the OpenAI organization/workspace association. The MCP process uses stdio and has no public network listener.</p><p>Keep this Mac awake for Garmin requests. Your Garmin password is discarded after login. Re-enter the runtime key here if the tunnel needs to be restarted.</p></section>
<script nonce="__NONCE__">
const csrf='__CSRF__';
async function post(path,data){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Setup-CSRF':csrf},body:JSON.stringify(data)});const result=await r.json();if(!r.ok)throw new Error(result.error||'Request failed');return result;}
document.getElementById('login').onsubmit=async e=>{e.preventDefault();const pw=document.getElementById('password');const data={email:document.getElementById('email').value,password:pw.value};pw.value='';try{await post('/login',data);}catch(e){alert(e.message)}data.password='';};
document.getElementById('mfa').onsubmit=async e=>{e.preventDefault();const field=document.getElementById('code');const code=field.value;field.value='';try{await post('/mfa',{code});}catch(e){alert(e.message)}};
document.getElementById('tunnel').onsubmit=async e=>{e.preventDefault();const key=document.getElementById('runtimeKey');const data={tunnel_id:document.getElementById('tunnelId').value,key:key.value};key.value='';try{await post('/tunnel',data);}catch(e){alert(e.message)}data.key='';};
async function refresh(){try{const r=await fetch('/status');const s=await r.json();document.getElementById('garminStatus').textContent=s.garmin;document.getElementById('tunnelStatus').textContent=s.tunnel;document.getElementById('mfa').hidden=!s.needs_mfa;if(!document.getElementById('tunnelId').value)document.getElementById('tunnelId').value=s.tunnel_id||'';}catch(e){}setTimeout(refresh,2000)}refresh();
</script></html>"""


class Setup:
    def __init__(self):
        self.csrf = secrets.token_urlsafe(32)
        self.session = secrets.token_urlsafe(32)
        self.nonce = secrets.token_urlsafe(24)
        self.lock = threading.Lock()
        self.mfa_event = threading.Event()
        self.mfa_code = None
        self.login_active = False
        self.needs_mfa = False
        self.garmin = "Not connected"
        self.tunnel = "Not started"
        self.tunnel_id = ""
        self.tunnel_active = False
        if CONFIG.is_file():
            self.tunnel_id = json.loads(CONFIG.read_text()).get("tunnel_id", "")
        if (DATA / "garmin/garmin_tokens.json").is_file():
            self.garmin = "Saved Garmin session found"

    def authorized(self, request, write=False):
        if request.headers.get("host") != "127.0.0.1:8766":
            return False
        if not secrets.compare_digest(request.cookies.get("setup_session", ""), self.session):
            return False
        if write:
            return (request.headers.get("origin") == ORIGIN and
                    secrets.compare_digest(request.headers.get("x-setup-csrf", ""), self.csrf))
        return True

    def prompt_mfa(self):
        self.mfa_event.clear()
        self.mfa_code = None
        self.needs_mfa = True
        self.garmin = "Enter the Garmin MFA code below."
        if not self.mfa_event.wait(300):
            raise TimeoutError("MFA timed out")
        code, self.mfa_code = self.mfa_code, None
        self.needs_mfa = False
        return code

    def login(self, email, password):
        try:
            directory = DATA / "garmin"
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory.chmod(0o700)
            client = Garmin(email=email, password=password, prompt_mfa=self.prompt_mfa)
            password = None
            client.login(str(directory))
            # Verify a read succeeds, without exposing the returned data to the UI.
            client.get_activities(start=0, limit=1)
            self.garmin = "Connected. Live Garmin read verified; session saved on this Mac."
        except Exception:
            self.garmin = "Garmin login/read failed. Check credentials and MFA, or try again later."
        finally:
            password = None
            self.needs_mfa = False
            self.login_active = False

    def start_tunnel(self, tunnel_id, key):
        env = os.environ.copy()
        env["CONTROL_PLANE_API_KEY"] = key
        key = None
        command = shlex.join([str(ROOT / ".venv/bin/python"), "-m", "garmin_mcp.local"])
        try:
            args = [str(TUNNEL), "runtimes", "connect", "--alias", "personal-garmin",
                    "--tunnel-id", tunnel_id, "--profile", "personal-garmin",
                    "--profile-dir", str(DATA / "profiles"),
                    "--mcp-command", command, "--runtime-api-key", "env:CONTROL_PLANE_API_KEY", "--json"]
            log_path = DATA / "tunnel-setup.log"
            with log_path.open("a") as log:
                result = subprocess.run(args, cwd=ROOT, env=env, stdout=log, stderr=log, timeout=90)
            if result.returncode:
                self.tunnel = "Tunnel could not start. Check key permissions (Tunnels Read + Use) and the tunnel ID."
                return
            self.tunnel = "Tunnel started. Checking readiness…"
            # No key is needed for local managed-runtime inspection.
            for _ in range(20):
                result = subprocess.run([str(TUNNEL), "runtimes", "status", "personal-garmin", "--json"],
                    cwd=ROOT, capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    status = json.loads(result.stdout)
                    # Preserve only local diagnostic state, never the credential.
                    (DATA / "runtime-status.json").write_text(json.dumps(status))
                    if contains_ready(status):
                        self.tunnel = "Ready. The private tunnel is running; connect it in ChatGPT."
                        return
                threading.Event().wait(1)
            self.tunnel = "Tunnel launched but readiness is not yet confirmed. Local diagnostics are available for review."
        except Exception:
            self.tunnel = "Tunnel setup failed. Check local diagnostics and retry."
        finally:
            env.pop("CONTROL_PLANE_API_KEY", None)
            self.tunnel_active = False


def contains_ready(value):
    if isinstance(value, dict):
        if value.get("ready") is True:
            return True
        return any(contains_ready(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_ready(v) for v in value)
    return False


def create_setup(state=None):
    state = state or Setup()

    async def index(request):
        if request.headers.get("host") != "127.0.0.1:8766":
            return JSONResponse({"error": "Invalid host"}, status_code=403)
        response = HTMLResponse(PAGE.replace("__CSRF__", state.csrf).replace("__NONCE__", state.nonce))
        response.set_cookie("setup_session", state.session, httponly=True, samesite="strict")
        response.headers["Content-Security-Policy"] = f"default-src 'none'; script-src 'nonce-{state.nonce}'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    async def status(request):
        if not state.authorized(request):
            return JSONResponse({"error": "Local session required"}, status_code=403)
        return JSONResponse({"garmin": state.garmin, "needs_mfa": state.needs_mfa,
                             "tunnel": state.tunnel, "tunnel_id": state.tunnel_id}, headers={"Cache-Control": "no-store"})

    async def action(request: Request):
        if not state.authorized(request, write=True):
            return JSONResponse({"error": "Local session and CSRF validation required"}, status_code=403)
        body = await request.body()
        if len(body) > 8192:
            return JSONResponse({"error": "Request too large"}, status_code=413)
        try:
            data = json.loads(body)
        except ValueError:
            return JSONResponse({"error": "Invalid input"}, status_code=400)
        with state.lock:
            if request.url.path == "/login":
                if state.login_active:
                    return JSONResponse({"error": "Login already in progress"}, status_code=409)
                if not data.get("email") or not data.get("password"):
                    return JSONResponse({"error": "Email and password are required"}, status_code=400)
                state.login_active = True
                state.garmin = "Signing in to Garmin…"
                threading.Thread(target=state.login, args=(data["email"], data["password"]), daemon=True).start()
            elif request.url.path == "/mfa":
                if not state.needs_mfa or not data.get("code"):
                    return JSONResponse({"error": "No MFA request is waiting"}, status_code=400)
                state.mfa_code = str(data["code"])
                state.mfa_event.set()
            elif request.url.path == "/tunnel":
                if state.tunnel_active:
                    return JSONResponse({"error": "Tunnel setup already in progress"}, status_code=409)
                if not re.fullmatch(r"tunnel_[a-zA-Z0-9]+", data.get("tunnel_id", "")) or not data.get("key", "").startswith("sk-"):
                    return JSONResponse({"error": "Enter a valid tunnel ID and runtime API key"}, status_code=400)
                state.tunnel_id = data["tunnel_id"]
                CONFIG.write_text(json.dumps({"tunnel_id": state.tunnel_id}))
                CONFIG.chmod(0o600)
                state.tunnel_active = True
                state.tunnel = "Starting the private tunnel…"
                threading.Thread(target=state.start_tunnel, args=(state.tunnel_id, data["key"]), daemon=True).start()
        return JSONResponse({"ok": True})

    return Starlette(routes=[Route("/", index), Route("/status", status),
        Route("/login", action, methods=["POST"]), Route("/mfa", action, methods=["POST"]),
        Route("/tunnel", action, methods=["POST"])])


def main():
    os.umask(0o077)
    DATA.mkdir(mode=0o700, exist_ok=True)
    DATA.chmod(0o700)
    uvicorn.run(create_setup(), host="127.0.0.1", port=8766, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
