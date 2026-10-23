import os
from getpass import getpass
from pathlib import Path
from dotenv import load_dotenv
from garminconnect import Garmin


def main():
    load_dotenv()
    os.umask(0o077)
    token_dir = Path(os.getenv("GARMIN_TOKEN_DIR", ".data/garmin")).expanduser()
    token_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    token_dir.chmod(0o700)
    client = Garmin(email=input("Garmin email: ").strip(), password=getpass("Garmin password: "),
                    prompt_mfa=lambda: input("Garmin MFA code: ").strip())
    try:
        client.login(str(token_dir))
    except Exception:
        raise SystemExit("Garmin login failed. Check credentials/MFA and connectivity; no credentials were printed.") from None
    print("Garmin session saved locally. You can now start garmin-mcp.")
