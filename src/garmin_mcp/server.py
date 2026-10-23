import os
from urllib.parse import urlsplit
from pathlib import Path
import fastmcp
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth.providers.google import GoogleProvider
from .history import History, Metric


class PersonalGoogleProvider(GoogleProvider):
    """Reject every identity except the configured verified Google account."""
    def __init__(self, allowed_email: str, **kwargs):
        self.allowed_email = allowed_email.strip().casefold()
        super().__init__(**kwargs)

    async def load_access_token(self, token):
        result = await super().load_access_token(token)
        if result is None:
            return None
        user = result.claims.get("google_user_data", {})
        if user.get("verified_email") is not True:
            return None
        if str(user.get("email", "")).casefold() != self.allowed_email:
            return None
        return result


def create_server(history: History, auth=None) -> FastMCP:
    server = FastMCP("Personal Garmin History", auth=auth,
        instructions="Read-only Garmin history. Page activities for older workouts. Request health metrics in windows of at most 31 days. Missing data is not zero. Activity distances are meters and durations seconds.")
    annotations = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}

    @server.tool(annotations=annotations)
    def list_activities(offset: int = 0, limit: int = 50, activity_type: str | None = None) -> dict:
        """Read historical workouts, newest first; paginate using next_offset. Optional type: running, cycling, swimming. Routes and coordinates are omitted."""
        return history.activities(offset, limit, activity_type)

    @server.tool(annotations=annotations)
    def get_activity(activity_id: int) -> dict:
        """Read one workout's full summary by its activityId. May include location details."""
        if activity_id <= 0:
            from fastmcp.exceptions import ToolError
            raise ToolError("activity_id must be positive.")
        return history.call("get_activity", str(activity_id))

    @server.tool(annotations=annotations)
    def get_health_history(metric: Metric, start_date: str, end_date: str) -> dict:
        """Read daily Garmin health and fitness history on inclusive YYYY-MM-DD dates: summary, sleep, heart_rate, stress, hrv, vo2_max (running/cycling when available), training_load (status and acute/chronic load), training_load_focus (trailing four weeks), training_readiness, weight (weigh-ins), body_composition, or fitness_age. Maximum 31 days per call; use smaller windows for detailed data. Missing device-supported metrics are unavailable, not zero. Weight may be in grams; preserve upstream units."""
        return history.health(metric, start_date, end_date)

    return server


def main():
    load_dotenv()
    os.umask(0o077)
    names = ["MCP_BASE_URL", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "ALLOWED_GOOGLE_EMAIL", "MCP_SIGNING_KEY"]
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        raise SystemExit("Missing configuration: " + ", ".join(missing))
    base = os.environ["MCP_BASE_URL"].rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
        raise SystemExit("MCP_BASE_URL must be an HTTPS origin without a path, query, or fragment.")
    if len(os.environ["MCP_SIGNING_KEY"]) < 32:
        raise SystemExit("MCP_SIGNING_KEY must contain at least 32 random characters.")
    fastmcp.settings.home = Path(".data/mcp").absolute()
    fastmcp.settings.home.mkdir(parents=True, exist_ok=True, mode=0o700)
    fastmcp.settings.home.chmod(0o700)
    auth = PersonalGoogleProvider(allowed_email=os.environ["ALLOWED_GOOGLE_EMAIL"],
        client_id=os.environ["GOOGLE_CLIENT_ID"], client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        base_url=base, required_scopes=["openid", "https://www.googleapis.com/auth/userinfo.email"],
        jwt_signing_key=os.environ["MCP_SIGNING_KEY"], require_authorization_consent=True)
    server = create_server(History(os.getenv("GARMIN_TOKEN_DIR", ".data/garmin")), auth)
    server.run(transport="http", host=os.getenv("MCP_HOST", "127.0.0.1"),
               port=int(os.getenv("MCP_PORT", "8000")), path="/mcp", show_banner=False)
