"""Sign in with Google or GitHub (the OAuth 2.0 authorization code flow).

1. The dashboard sends the browser to /api/auth/oauth/{provider}/start. It sets
   a short-lived cookie holding a random state, and redirects to the provider.
2. The provider sends the browser back to /callback with a code and the same
   state. The state must match the cookie, which stops another site from
   finishing a sign-in on someone's behalf.
3. The code is exchanged for the account's verified email; the account is found
   or created, and the browser returns to the dashboard with the session in the
   URL fragment (#auth=...), which browsers never send to a server.

A provider is offered only when both its client ID and secret are set.
"""
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

PROVIDERS = {
    "google": {"authorize": "https://accounts.google.com/o/oauth2/v2/auth",
               "token": "https://oauth2.googleapis.com/token", "scope": "openid email profile"},
    "github": {"authorize": "https://github.com/login/oauth/authorize",
               "token": "https://github.com/login/oauth/access_token", "scope": "read:user user:email"},
}
COOKIE = "tervik_oauth"
COOKIE_PATH = "/api/auth/oauth"


class OAuthError(Exception):
    """A sign-in that can't finish, with a reason fit to show the person."""


def http_json(method, url, *, data=None, headers=None, timeout=15):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, method=method,
                                     headers={"Accept": "application/json", "User-Agent": "Tervik", **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def credentials(settings, provider):
    """(client ID, secret) for a configured provider, else None."""
    pair = {"google": (settings.google_client_id, settings.google_client_secret),
            "github": (settings.github_client_id, settings.github_client_secret)}.get(provider)
    return pair if pair and all(pair) else None


def verified_email(provider, code, redirect_uri, client, transport):
    """Exchange the code for the account's verified email, and its name when known."""
    client_id, client_secret = client
    token = transport("POST", PROVIDERS[provider]["token"], data={
        "code": code, "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
    access = token.get("access_token")
    if not access:
        raise OAuthError("The sign-in code expired. Try again.")
    if provider == "google":
        info = transport("GET", "https://openidconnect.googleapis.com/v1/userinfo",
                         headers={"Authorization": f"Bearer {access}"})
        if not info.get("email") or not info.get("email_verified"):
            raise OAuthError("Your Google account has no verified email address.")
        return info["email"], info.get("name")
    headers = {"Authorization": f"Bearer {access}", "Accept": "application/vnd.github+json"}
    emails = transport("GET", "https://api.github.com/user/emails", headers=headers)
    verified = [e for e in emails if isinstance(e, dict) and e.get("verified") and e.get("email")]
    if not verified:
        raise OAuthError("Your GitHub account has no verified email address.")
    chosen = next((e for e in verified if e.get("primary")), verified[0])
    profile = transport("GET", "https://api.github.com/user", headers=headers)
    return chosen["email"], profile.get("name") or profile.get("login")


def register(app, *, sessions, settings, sign_in, allowed_origins):
    """Add the provider list and the sign-in routes. sign_in(db_session, email, name)
    returns a session token, creating the account first if needed."""
    app.state.oauth_transport = http_json

    def safe_return(url):
        """Only send people back to a dashboard this API serves."""
        parts = urllib.parse.urlsplit(url or "")
        origin = f"{parts.scheme}://{parts.netloc}"
        return url if parts.scheme in ("http", "https") and origin in allowed_origins() else settings.dashboard_url

    def callback_url(request, provider):
        base = (settings.public_api_url or str(request.base_url)).rstrip("/")
        return f"{base}{COOKIE_PATH}/{provider}/callback"

    @app.get("/api/auth/providers")
    def providers():
        return {"google": credentials(settings, "google") is not None,
                "github": credentials(settings, "github") is not None,
                "signup": settings.signup_enabled}

    @app.get("/api/auth/oauth/{provider}/start")
    def start(request: Request, provider: str, return_to: str = ""):
        client = credentials(settings, provider)
        if client is None:
            raise HTTPException(404, "This sign-in option isn't set up")
        state = secrets.token_urlsafe(24)
        query = urllib.parse.urlencode({
            "client_id": client[0], "redirect_uri": callback_url(request, provider), "response_type": "code",
            "scope": PROVIDERS[provider]["scope"], "state": state,
            **({"prompt": "select_account"} if provider == "google" else {"allow_signup": "true"})})
        response = RedirectResponse(f'{PROVIDERS[provider]["authorize"]}?{query}', status_code=302)
        response.set_cookie(COOKIE, f"{state}|{urllib.parse.quote(safe_return(return_to), safe='')}", max_age=600,
                            path=COOKIE_PATH, httponly=True, samesite="lax", secure=request.url.scheme == "https")
        return response

    @app.get("/api/auth/oauth/{provider}/callback")
    def callback(request: Request, provider: str, code: str = "", state: str = "", error: str = ""):
        expected, _, saved = request.cookies.get(COOKIE, "").partition("|")
        return_to = safe_return(urllib.parse.unquote(saved))

        def finish(fragment):
            response = RedirectResponse(f"{return_to.split('#')[0]}#{fragment}", status_code=302)
            response.delete_cookie(COOKIE, path=COOKIE_PATH)
            return response

        def failed(reason):
            return finish("auth-error=" + urllib.parse.quote(reason))

        client = credentials(settings, provider)
        if client is None:
            return failed("This sign-in option isn't set up.")
        if error:
            return failed("Sign-in was cancelled.")
        if not code or not state or not expected or not secrets.compare_digest(state, expected):
            return failed("That sign-in link expired. Try again.")
        try:
            email, name = verified_email(provider, code, callback_url(request, provider), client, app.state.oauth_transport)
            with sessions.begin() as db_session:
                token = sign_in(db_session, email, name)
        except OAuthError as reason:
            return failed(str(reason))
        except HTTPException as refused:
            return failed(str(refused.detail))
        except (urllib.error.URLError, ValueError, KeyError, TypeError):
            return failed(f"{provider.title()} didn't answer. Try again.")
        return finish("auth=" + token)
