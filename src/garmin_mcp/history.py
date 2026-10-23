from datetime import date, timedelta
from pathlib import Path
from threading import RLock
from typing import Literal

from fastmcp.exceptions import ToolError
from garminconnect import Garmin

from .samples import CHART_LIMIT, decode_samples

Metric = Literal["summary", "sleep", "heart_rate", "stress", "hrv", "vo2_max", "training_load", "training_load_focus", "training_readiness", "weight", "body_composition", "fitness_age"]
METHODS = {
    "summary": "get_stats", "sleep": "get_sleep_data",
    "heart_rate": "get_heart_rates", "stress": "get_stress_data", "hrv": "get_hrv_data",
    "vo2_max": "get_max_metrics", "training_load": "get_daily_training_status",
    "training_load_focus": "get_training_four_week_load_balance",
    "training_readiness": "get_training_readiness", "weight": "get_daily_weigh_ins",
    "body_composition": "get_body_composition", "fitness_age": "get_fitnessage_data",
}


def date_range(start: str, end: str, max_days: int = 31) -> list[str]:
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if first.isoformat() != start or last.isoformat() != end:
            raise ValueError
    except ValueError:
        raise ToolError("Use dates in YYYY-MM-DD format.") from None
    days = (last - first).days + 1
    if not 1 <= days <= max_days:
        raise ToolError(f"Use an inclusive date range of 1–{max_days} days; split longer history into windows.")
    return [(first + timedelta(days=i)).isoformat() for i in range(days)]


class History:
    def __init__(self, token_dir: str, client=None):
        self.token_dir = str(Path(token_dir).expanduser())
        self.client = client
        self.lock = RLock()

    def call(self, method: str, *args, **kwargs):
        # Serialize access: Garmin refreshes and writes shared session tokens.
        with self.lock:
            try:
                if self.client is None:
                    if not (Path(self.token_dir) / "garmin_tokens.json").is_file():
                        raise ToolError("Run garmin-login locally before requesting history.")
                    client = Garmin()
                    client.login(self.token_dir)
                    self.client = client
                return getattr(self.client, method)(*args, **kwargs)
            except ToolError:
                raise
            except Exception:
                # Raw upstream errors may contain private response details.
                raise ToolError("Garmin request failed. Check connectivity, rate limits, and saved login; retry later or run garmin-login.") from None

    def activities(self, offset: int = 0, limit: int = 50, activity_type: str | None = None):
        if offset < 0 or not 1 <= limit <= 100:
            raise ToolError("offset must be nonnegative and limit must be 1–100.")
        data = self.call("get_activities", start=offset, limit=limit, activitytype=activity_type)
        items = data.get("activityList", []) if isinstance(data, dict) else data
        # Exclude coordinates, routes, account identifiers, and other unneeded fields.
        fields = ("activityId", "activityName", "activityType", "startTimeLocal", "startTimeGMT", "distance", "duration", "movingDuration", "averageHR", "maxHR", "averageSpeed", "elevationGain", "calories")
        return {"activities": [{k: item[k] for k in fields if k in item} for item in items],
                "offset": offset, "next_offset": offset + len(items) if len(items) == limit else None,
                "units": {"distance": "meters", "duration": "seconds", "speed": "meters/second"},
                "note": "Newest first. Continue with next_offset until null to retrieve older history."}

    def get_activity_samples(self, activity_id: int, max_points: int = 2000,
                             interval_seconds: int | None = None) -> dict:
        if type(activity_id) is not int or activity_id <= 0:
            raise ToolError("activity_id must be a positive integer.")
        if type(max_points) is not int or not 2 <= max_points <= CHART_LIMIT:
            raise ToolError(f"max_points must be an integer from 2 to {CHART_LIMIT}.")
        if interval_seconds is not None and (type(interval_seconds) is not int or not 1 <= interval_seconds <= 86400):
            raise ToolError("interval_seconds must be an integer from 1 to 86400, or null.")
        data = self.call("get_activity_details", str(activity_id), maxchart=CHART_LIMIT, maxpoly=0)
        return {"activity_id": activity_id, **decode_samples(data, max_points, interval_seconds)}

    def health(self, metric: Metric, start_date: str, end_date: str):
        dates = date_range(start_date, end_date)
        if metric not in METHODS:
            raise ToolError("Unsupported health metric.")
        return {"metric": metric, "days": [{"date": day, "data": self.call(METHODS[metric], day)} for day in dates],
                "note": "Dates follow Garmin account calendar dates. Empty data means unavailable, not zero. Values and units are returned as supplied by Garmin; weight fields may be grams. VO2 max may be sparse; do not treat missing days as zero. Load focus is the trailing four-week period ending on each date."}
