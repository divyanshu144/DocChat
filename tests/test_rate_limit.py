import pytest
from fastapi.testclient import TestClient
from app.core.config import settings


def test_rate_limiter_expires_windows_and_isolates_keys():
    from app.core.rate_limit import RateLimiter

    limiter = RateLimiter(max_keys=2)
    assert limiter.check(("login", "ip-a"), 2, 60, now=0) == 0
    assert limiter.check(("login", "ip-a"), 2, 60, now=1) == 0
    assert limiter.check(("login", "ip-a"), 2, 60, now=2) == 58
    assert limiter.check(("chat", "ip-a"), 2, 60, now=2) == 0
    assert limiter.check(("login", "ip-b"), 2, 60, now=2) == 60  # bounded, fail closed
    assert limiter.check(("login", "ip-a"), 2, 60, now=60) == 0



@pytest.mark.parametrize("path,setting", [("auth/login", "login_rate_limit"), ("auth/signup", "signup_rate_limit"), ("chat", "chat_rate_limit")])
def test_rate_limits_are_wired_to_routes(path, setting, monkeypatch):
    from app.main import app

    monkeypatch.setattr(settings, setting, 1)
    client = TestClient(app)
    client.post(f"/api/v1/{path}", json={})
    response = client.post(f"/api/v1/{path}", json={})
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
