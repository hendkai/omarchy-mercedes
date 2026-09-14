"""Mercedes-Benz OAuth2 client, modeled on mbapi2020's oauth.py (MIT).

Flow (verified against mbapi2020 master, 2026-09):
 1. GET {login}/as/authorization.oauth2 with PKCE + client_id + redirect_uri
    (rismycar://login-callback) -> CIAM login page; keep the `resume` query
    parameter and session cookies.
 2. POST /ciam/auth/ua           (browser info)
 3. POST /ciam/auth/login/user   (username)
 4. POST /ciam/auth/login/pass   (password) -> JSON with pre-login token.
    result may be RESUME2OIDCP (ok), GOTO_LOGIN_OTP (2FA enforced),
    GOTO_LOGIN_LEGAL_TEXTS (consent required) or passkeyDemoEnabled.
 5. POST {login}{resume} form token -> 302 Location: rismycar://...?code=...
 6. POST /as/token.oauth2 (authorization_code + code_verifier) -> tokens
 Refresh: POST /as/token.oauth2 grant_type=refresh_token. A new
 refresh_token may be returned (rotation); we keep the old one as fallback.

This module is stdlib+requests only and never logs secrets.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
import urllib.parse
import uuid

from .api_constants import LOGIN_APP_ID, LOGIN_BASE_URL, OAUTH_REDIRECT_URI, OAUTH_SCOPE

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


class AuthError(RuntimeError):
    """Any authentication failure (bad credentials, network, server)."""


class TwoFactorRequiredError(AuthError):
    """Account enforces OTP 2FA; use the browser login flow instead."""


class LegalTermsError(AuthError):
    """Legal consent must be accepted; use the browser login flow."""


SAFARI_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_8_3 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/15.6.6 Mobile/15E148 Safari/604.1"
)


def _basic_headers(base_url: str, referer: bool = True) -> dict:
    h = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": base_url,
        "accept-language": "de-DE,de;q=0.9",
        "user-agent": SAFARI_UA,
    }
    if referer:
        h["referer"] = f"{base_url}/ciam/auth/login"
    return h


class MercedesOAuthClient:
    """Login, token exchange and refresh against the Mercedes CIAM IdP."""

    def __init__(self, region: str = "eu", timeout: int = 30, session=None):
        if region not in LOGIN_BASE_URL:
            raise ValueError(f"unsupported region {region!r}")
        self.region = region
        self.base = LOGIN_BASE_URL[region]
        self.client_id = LOGIN_APP_ID[region]
        self.timeout = timeout
        self.device_guid = str(uuid.uuid4())
        self._session = session

    # -- plumbing -----------------------------------------------------------
    def _http(self):
        if self._session is None:
            if requests is None:
                raise AuthError(
                    "the 'requests' package is required for login (pip install requests)"
                )
            self._session = requests.Session()
            self._session.cookies.set("CIAM.DEVICE", self.device_guid)
        return self._session

    def _request(self, method: str, url: str, **kw):
        try:
            return self._http().request(method, url, timeout=self.timeout, **kw)
        except AuthError:
            raise
        except Exception as e:  # network/DNS/TLS
            raise AuthError(f"network error during {method}: {type(e).__name__}") from e

    # -- PKCE -----------------------------------------------------------------
    @staticmethod
    def _pkce() -> tuple[str, str]:
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).decode().rstrip("=")
        return verifier, challenge

    # -- login -----------------------------------------------------------------
    def login_with_password(self, email: str, password: str) -> dict:
        """Headless password login. Raises TwoFactorRequiredError if OTP is enforced."""
        verifier, challenge = self._pkce()
        s = self._http()

        params = {
            "client_id": self.client_id,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "redirect_uri": OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": OAUTH_SCOPE,
        }
        r = self._request(
            "GET",
            f"{self.base}/as/authorization.oauth2",
            params=params,
            headers={
                "user-agent": SAFARI_UA,
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "accept-language": "de-DE,de;q=0.9",
            },
            allow_redirects=True,
        )
        if r.status_code >= 400:
            raise AuthError(f"authorization request failed: HTTP {r.status_code}")
        resume = urllib.parse.parse_qs(urllib.parse.urlparse(r.url).query).get("resume", [None])[0]
        if not resume:
            raise AuthError("no resume parameter in authorization response")

        self._request(
            "POST",
            f"{self.base}/ciam/auth/ua",
            json={"browserName": "Mobile Safari", "browserVersion": "15.6.6", "osName": "iOS"},
            headers=_basic_headers(self.base, referer=False),
        )

        r = self._request(
            "POST",
            f"{self.base}/ciam/auth/login/user",
            json={"username": email},
            headers=_basic_headers(self.base),
        )
        if r.status_code >= 400:
            raise AuthError(f"username step failed: HTTP {r.status_code}")

        rid = secrets.token_urlsafe(24)
        r = self._request(
            "POST",
            f"{self.base}/ciam/auth/login/pass",
            json={"username": email, "password": password, "rememberMe": False, "rid": rid},
            headers=_basic_headers(self.base),
        )
        if r.status_code >= 400:
            raise AuthError(f"password step failed: HTTP {r.status_code}")
        try:
            pre = r.json()
        except ValueError as e:
            raise AuthError("password step returned invalid JSON") from e

        if pre.get("passkeyDemoEnabled"):
            r = self._request(
                "POST",
                f"{self.base}/ciam/auth/disablePasskeyDemo",
                json={
                    "username": email,
                    "password": password,
                    "rememberMe": False,
                    "rid": rid,
                    "disablePasskeyDemo": True,
                },
                headers=_basic_headers(self.base),
            )
            if r.status_code < 400:
                try:
                    pre = r.json()
                except ValueError:
                    pass

        result = pre.get("result", "")
        if result == "GOTO_LOGIN_OTP":
            raise TwoFactorRequiredError("account enforces OTP second factor")
        if result == "GOTO_LOGIN_LEGAL_TEXTS":
            raise LegalTermsError("legal consent required before login completes")
        if result != "RESUME2OIDCP":
            raise AuthError(f"unexpected login result: {result!r}")
        if "token" not in pre:
            raise AuthError("pre-login token missing from CIAM response")

        code = self._resume_authorization(resume, pre["token"], s)
        return self.exchange_code(code, verifier)

    def _resume_authorization(self, resume_path: str, token: str, session) -> str:
        headers = _basic_headers(self.base)
        headers["accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        headers["content-type"] = "application/x-www-form-urlencoded"
        try:
            r = session.post(
                f"{self.base}{resume_path}",
                data={"token": token},
                headers=headers,
                allow_redirects=False,
                timeout=self.timeout,
            )
        except Exception as e:
            raise AuthError(f"network error during resume: {type(e).__name__}") from e
        loc = r.headers.get("Location", "")
        if loc.startswith("rismycar://"):
            code = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query).get("code", [None])[0]
            if code:
                return code
        raise AuthError("no authorization code in redirect (login rejected?)")

    # -- token endpoint -----------------------------------------------------
    def exchange_code(self, code: str, code_verifier: str) -> dict:
        data = {
            "client_id": self.client_id,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": OAUTH_REDIRECT_URI,
        }
        tok = self._token_request(data)
        tok.setdefault("refresh_token", None)
        return tok

    def refresh(self, refresh_token: str) -> dict:
        """Refresh access token. Raises AuthError when the session was revoked."""
        tok = self._token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )
        if "refresh_token" not in tok or not tok["refresh_token"]:
            tok["refresh_token"] = refresh_token  # backend did not rotate
        tok["refresh_rotated"] = tok["refresh_token"] != refresh_token
        return tok

    def _token_request(self, data: dict) -> dict:
        r = self._request(
            "POST",
            f"{self.base}/as/token.oauth2",
            data=data,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        if r.status_code in (400, 401, 403):
            raise AuthError(f"token endpoint rejected request: HTTP {r.status_code}")
        if r.status_code >= 400:
            raise AuthError(f"token endpoint failed: HTTP {r.status_code}")
        try:
            tok = r.json()
        except ValueError as e:
            raise AuthError("token endpoint returned invalid JSON") from e
        if "access_token" not in tok:
            raise AuthError("token endpoint response missing access_token")
        tok["expires_at"] = int(time.time()) + int(tok.get("expires_in", 0))
        return tok


_SECRET_KEYS = {
    "access_token",
    "refresh_token",
    "id_token",
    "password",
    "code_verifier",
    "authorization",
    "cookie",
    "set-cookie",
    "nonce",
    "pin",
    "otp",
    "code",
}


def redact(obj):
    """Recursively redact secret-like values so tokens never reach logs."""
    if isinstance(obj, dict):
        return {k: ("***REDACTED***" if str(k).lower() in _SECRET_KEYS else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        # JWT-like strings: three long base64url segments
        if obj.count(".") == 2 and len(obj) > 60 and all(len(p) > 20 for p in obj.split(".")):
            return "***REDACTED-JWT***"
        return obj
    return obj
