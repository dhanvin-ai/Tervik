"""Sign in with Google and GitHub, against a fake provider."""
from urllib.parse import parse_qs, unquote, urlsplit

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

DASHBOARD = "https://www.tervik.in/"


def make(tmp_path, **values):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'oauth.db'}", admin_token="admin-secret",
                        dashboard_url="https://www.tervik.in", cors_origins=("https://www.tervik.in",), **values)
    app = create_app(settings)
    return app, TestClient(app, base_url="https://api.tervik.in")


def fake_provider(email="ada@example.com", verified=True):
    calls = []
    def transport(method, url, *, data=None, headers=None, timeout=15):
        calls.append((method, url, data))
        if "token" in url:
            return {"access_token": "provider-token"} if data["code"] == "good-code" else {"error": "bad_verification_code"}
        if url.endswith("/userinfo"):
            return {"email": email, "email_verified": verified, "name": "Ada"}
        if url.endswith("/user/emails"):
            return [{"email": "old@example.com", "verified": True, "primary": False},
                    {"email": email, "verified": verified, "primary": True}]
        if url.endswith("/user"):
            return {"login": "ada"}
        raise AssertionError(url)
    return transport, calls


def start(client, provider, return_to=DASHBOARD):
    response = client.get(f"/api/auth/oauth/{provider}/start", params={"return_to": return_to}, follow_redirects=False)
    assert response.status_code == 302, response.text
    return parse_qs(urlsplit(response.headers["location"]).query), response


def finish(client, provider, state, code="good-code"):
    response = client.get(f"/api/auth/oauth/{provider}/callback", params={"code": code, "state": state}, follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    base, _, fragment = location.partition("#")
    return base, unquote(fragment)


def test_providers_are_offered_only_when_configured(tmp_path):
    _, client = make(tmp_path)
    assert client.get("/api/auth/providers").json() == {"google": False, "github": False, "signup": True}
    assert client.get("/api/auth/oauth/google/start", follow_redirects=False).status_code == 404
    _, client = make(tmp_path, google_client_id="id", google_client_secret="secret")
    assert client.get("/api/auth/providers").json()["google"] is True


def test_google_sign_in_creates_the_account_once_and_returns_a_session(tmp_path):
    app, client = make(tmp_path, google_client_id="gid", google_client_secret="gsecret")
    app.state.oauth_transport, calls = fake_provider()
    query, response = start(client, "google")
    assert query["client_id"] == ["gid"] and query["redirect_uri"] == ["https://api.tervik.in/api/auth/oauth/google/callback"]
    assert "httponly" in response.headers["set-cookie"].lower() and "secure" in response.headers["set-cookie"].lower()
    base, fragment = finish(client, "google", query["state"][0])
    assert base == DASHBOARD and fragment.startswith("auth=tvs_")
    session = fragment.removeprefix("auth=")
    me = client.get("/api/me", headers={"Authorization": f"Bearer {session}"}).json()
    assert me["account"]["email"] == "ada@example.com" and me["organizations"][0]["role"] == "owner"
    # Signing in again reaches the same account.
    query, _ = start(client, "google")
    _, fragment = finish(client, "google", query["state"][0])
    again = client.get("/api/me", headers={"Authorization": f"Bearer {fragment.removeprefix('auth=')}"}).json()
    assert again["account"]["id"] == me["account"]["id"]
    assert ("POST", "https://oauth2.googleapis.com/token") in [(m, u) for m, u, _ in calls]


def test_github_uses_the_primary_verified_email(tmp_path):
    app, client = make(tmp_path, github_client_id="hid", github_client_secret="hsecret")
    app.state.oauth_transport, _ = fake_provider(email="dev@example.com")
    query, _ = start(client, "github")
    _, fragment = finish(client, "github", query["state"][0])
    me = client.get("/api/me", headers={"Authorization": f"Bearer {fragment.removeprefix('auth=')}"}).json()
    assert me["account"]["email"] == "dev@example.com"


def test_sign_in_is_refused_without_the_matching_state_or_a_verified_email(tmp_path):
    app, client = make(tmp_path, google_client_id="gid", google_client_secret="gsecret")
    app.state.oauth_transport, _ = fake_provider(verified=False)
    start(client, "google")
    _, fragment = finish(client, "google", "someone-elses-state")
    assert fragment.startswith("auth-error=") and "expired" in fragment
    # The cookie is single-use: each attempt starts afresh.
    query, _ = start(client, "google")
    _, fragment = finish(client, "google", query["state"][0])
    assert fragment == "auth-error=Your Google account has no verified email address."
    query, _ = start(client, "google")
    _, fragment = finish(client, "google", query["state"][0], code="bad-code")
    assert fragment == "auth-error=The sign-in code expired. Try again."


def test_sign_in_only_returns_to_the_dashboard(tmp_path):
    app, client = make(tmp_path, google_client_id="gid", google_client_secret="gsecret")
    app.state.oauth_transport, _ = fake_provider()
    query, _ = start(client, "google", return_to="https://evil.example/steal")
    base, fragment = finish(client, "google", query["state"][0])
    assert base == "https://www.tervik.in" and fragment.startswith("auth=")
