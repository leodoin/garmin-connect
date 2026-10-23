from unittest.mock import Mock, patch

import httpx
import pytest

from garmin_mcp.local_setup import ORIGIN, Setup, create_setup


@pytest.mark.asyncio
async def test_local_setup_rejects_remote_hosts_and_cross_origin_writes():
    state = Setup()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_setup(state)), base_url=ORIGIN) as client:
        response = await client.get("/", headers={"Host": "attacker.example"})
        assert response.status_code == 403
        response = await client.get("/status")
        assert response.status_code == 403
        response = await client.get("/")
        assert response.status_code == 200
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert "HttpOnly" in response.headers["set-cookie"]
        assert (await client.get("/status")).status_code == 200
        for headers in [{}, {"Origin": "https://attacker.example", "X-Setup-CSRF": state.csrf}, {"Origin": ORIGIN, "X-Setup-CSRF": "wrong"}]:
            assert (await client.post("/login", json={"email": "me@example.com", "password": "secret"}, headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_local_setup_never_returns_submitted_password():
    state = Setup()
    app = create_setup(state)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        await client.get("/")
        with patch("garmin_mcp.local_setup.threading.Thread") as worker:
            response = await client.post("/login", json={"email": "me@example.com", "password": "secret"},
                headers={"Origin": ORIGIN, "X-Setup-CSRF": state.csrf})
            assert response.status_code == 200
            worker.return_value.start.assert_called_once()
        status = await client.get("/status")
        assert "secret" not in status.text
        assert "me@example.com" not in status.text
        assert (await client.post("/login", json={"email": "me@example.com", "password": "secret"},
            headers={"Origin": ORIGIN, "X-Setup-CSRF": state.csrf})).status_code == 409


def test_garmin_login_verifies_read_and_sanitizes_failure(tmp_path):
    state = Setup()
    with patch("garmin_mcp.local_setup.DATA", tmp_path), patch("garmin_mcp.local_setup.Garmin") as factory:
        factory.return_value.get_activities.return_value = []
        state.login("me@example.com", "secret")
        assert "Live Garmin read verified" in state.garmin
        factory.return_value.get_activities.assert_called_once_with(start=0, limit=1)
        factory.return_value.login.side_effect = RuntimeError("SECRET")
        state.login("me@example.com", "secret")
        assert "failed" in state.garmin
        assert "SECRET" not in state.garmin
