from unittest.mock import Mock, AsyncMock, patch
from types import SimpleNamespace
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from garmin_mcp.history import History, date_range
from garmin_mcp.server import create_server, PersonalGoogleProvider


def test_date_validation():
    assert date_range("2024-02-28", "2024-03-01") == ["2024-02-28", "2024-02-29", "2024-03-01"]
    for start, end in [("2024-01-01", "2024-02-01"), ("2024-02-01", "2024-01-01"), ("bad", "2024-01-01")]:
        with pytest.raises(ToolError):
            date_range(start, end)


def test_pagination_and_privacy():
    client = Mock()
    client.get_activities.return_value = [{"activityId": 1, "startLatitude": 42}]
    result = History("unused", client).activities(50, 1)
    assert result["next_offset"] == 51
    assert result["activities"] == [{"activityId": 1}]
    client.get_activities.assert_called_once_with(start=50, limit=1, activitytype=None)


def test_failure_does_not_leak_secrets():
    client = Mock()
    client.get_stats.side_effect = RuntimeError("SECRET-TOKEN")
    with pytest.raises(ToolError) as error:
        History("unused", client).health("summary", "2024-01-01", "2024-01-01")
    assert "SECRET-TOKEN" not in str(error.value)


def test_missing_login(tmp_path):
    with pytest.raises(ToolError, match="garmin-login"):
        History(str(tmp_path)).call("get_stats", "2024-01-01")


@pytest.mark.asyncio
async def test_mcp_tools_and_calls():
    backend = Mock()
    backend.get_stats.return_value = {"totalSteps": 123}
    backend.get_activities.return_value = []
    async with Client(create_server(History("unused", backend))) as client:
        tools = await client.list_tools()
        assert {t.name for t in tools} == {"list_activities", "get_activity", "get_activity_samples", "get_health_history"}
        assert all(t.annotations.readOnlyHint for t in tools)
        result = await client.call_tool("get_health_history", {"metric": "summary", "start_date": "2024-01-01", "end_date": "2024-01-02"})
        assert len(result.data["days"]) == 2
        assert backend.get_stats.call_count == 2
        await client.call_tool("list_activities", {})
        with pytest.raises(Exception):
            await client.call_tool("get_activity", {"activity_id": -1})


@pytest.mark.asyncio
@pytest.mark.parametrize("email,verified,allowed", [("me@example.com", True, True), ("other@example.com", True, False), ("me@example.com", False, False), ("me@example.com", None, False)])
async def test_owner_only_auth(email, verified, allowed):
    provider = object.__new__(PersonalGoogleProvider)
    provider.allowed_email = "me@example.com"
    token = SimpleNamespace(claims={"google_user_data": {"email": email, "verified_email": verified}})
    with patch("fastmcp.server.auth.providers.google.GoogleProvider.load_access_token", new=AsyncMock(return_value=token)):
        assert (await provider.load_access_token("token") is not None) is allowed


@pytest.mark.asyncio
async def test_http_requires_oauth_and_publishes_discovery(tmp_path, monkeypatch):
    import fastmcp
    monkeypatch.setattr(fastmcp.settings, "home", tmp_path)
    import httpx
    auth = PersonalGoogleProvider(allowed_email="me@example.com", client_id="test-client",
        client_secret="test-secret", base_url="https://garmin.example.com",
        required_scopes=["openid", "https://www.googleapis.com/auth/userinfo.email"],
        jwt_signing_key="x" * 48)
    app = create_server(History("unused", Mock()), auth).http_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://garmin.example.com") as client:
        response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert response.status_code == 401
        assert "resource_metadata" in response.headers["www-authenticate"]
        discovery = await client.get("/.well-known/oauth-authorization-server")
        assert discovery.status_code == 200
        assert discovery.json()["authorization_endpoint"].startswith("https://garmin.example.com/")


@pytest.mark.parametrize("metric,method", [
    ("vo2_max", "get_max_metrics"),
    ("training_load", "get_daily_training_status"),
    ("training_load_focus", "get_training_four_week_load_balance"),
    ("training_readiness", "get_training_readiness"),
    ("weight", "get_daily_weigh_ins"),
    ("body_composition", "get_body_composition"),
    ("fitness_age", "get_fitnessage_data"),
])
def test_fitness_history_dispatch_and_missing_data(metric, method):
    backend = Mock()
    getattr(backend, method).return_value = []
    result = History("unused", backend).health(metric, "2024-01-01", "2024-01-02")
    assert [day["data"] for day in result["days"]] == [[], []]
    assert getattr(backend, method).call_args_list == [(("2024-01-01",),), (("2024-01-02",),)]
    with pytest.raises(ToolError):
        History("unused", backend).health(metric, "2024-01-01", "2024-02-01")
