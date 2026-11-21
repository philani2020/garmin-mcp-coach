"""Garmin Connect Personal API client used by the MCP server.

Auth flow:
  GARMIN_PERSONAL_API_KEY (env)  --POST /token-->  JWT access token (24h)
  The JWT is cached in memory, re-minted ~1h before its `exp`, and re-minted
  once more on any 401 (e.g. if the key was rotated mid-session).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_env() -> None:
    """Load `.env` from the project root (and the working directory), never overriding
    variables already set, e.g. by systemd's EnvironmentFile or the MCP client config."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv()


load_env()

log = logging.getLogger("garmin_mcp")

BASE_URL = os.environ.get("GARMIN_PERSONAL_API_BASE_URL", "https://personal.connectapi.garmin.com").rstrip("/")
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
API_KEY_ENV = "GARMIN_PERSONAL_API_KEY"
TIMEOUT = float(os.environ.get("GARMIN_TIMEOUT_SECONDS", "30"))
REFRESH_WINDOW_SECONDS = 60 * 60  # re-mint when < 1h of validity remains


class GarminError(Exception):
    pass


# --------------------------------------------------------------------------- #
# HTTP client with token minting
# --------------------------------------------------------------------------- #
class GarminClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT)
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    @staticmethod
    def _api_key() -> str:
        key = os.environ.get(API_KEY_ENV, "").strip()
        if not key:
            raise GarminError(
                f"{API_KEY_ENV} is not set. Create a key at "
                "https://connect.garmin.com/app/settings/personalApiToken and export it."
            )
        return key

    @staticmethod
    def _jwt_exp(token: str) -> float:
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
        except Exception:
            # Docs say tokens live 24h; fall back to that if exp can't be parsed.
            return time.time() + 24 * 3600

    async def _mint(self) -> None:
        resp = await self._http.post(
            TOKEN_PATH,
            headers={"Accept": "*/*", "Authorization": f"ApiKey {self._api_key()}"},
        )
        if resp.status_code >= 400:
            raise GarminError(f"Token mint failed: HTTP {resp.status_code}: {resp.text[:500]}")
        token = resp.text.strip()
        # Endpoint returns the raw JWT, but tolerate a JSON wrapper just in case.
        if token.startswith("{"):
            body = resp.json()
            token = body.get("access_token") or body.get("accessToken") or body.get("token") or ""
        if not token:
            raise GarminError("Token endpoint returned an empty token.")
        self._token = token
        self._expires_at = self._jwt_exp(token)
        log.info("Minted new access token, expires %s", time.ctime(self._expires_at))

    async def _bearer(self, force: bool = False) -> str:
        async with self._lock:
            if force or not self._token or self._expires_at - time.time() < REFRESH_WINDOW_SECONDS:
                await self._mint()
            return self._token  # type: ignore[return-value]

    async def request(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        accept: str = "application/json",
    ) -> httpx.Response:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        for attempt in (0, 1):
            token = await self._bearer(force=attempt == 1)
            resp = await self._http.get(
                path, params=params, headers={"Authorization": f"Bearer {token}", "Accept": accept}
            )
            if resp.status_code == 401 and attempt == 0:
                log.info("401 received, re-minting token and retrying")
                continue
            break
        if resp.status_code >= 400:
            raise GarminError(f"GET {path} -> HTTP {resp.status_code}: {resp.text[:1000]}")
        return resp

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        resp = await self.request(path, params)
        if not resp.content:
            return {"result": None, "note": "Empty response (no data recorded for this period)."}
        return resp.json()
