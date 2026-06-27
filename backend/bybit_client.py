"""
Thin async client around Bybit's V5 *public* market-data endpoints.

Only read-only market data is touched here (instruments-info, tickers).
No API key/secret is required or accepted in this module by design -- the
project is currently in "public data only" mode (see README "Roadmap").
Private endpoints (wallet balance, positions, order placement) belong in a
separate `bybit_private_client.py` added in Phase 2, gated behind explicit
user-supplied API keys.
"""
from __future__ import annotations

import httpx

from backend.config import BYBIT_BASE_URL, HTTP_TIMEOUT_SECONDS


class BybitAPIError(RuntimeError):
    def __init__(self, ret_code: int, ret_msg: str, endpoint: str):
        self.ret_code = ret_code
        self.ret_msg = ret_msg
        self.endpoint = endpoint
        super().__init__(f"Bybit API error on {endpoint}: [{ret_code}] {ret_msg}")


async def _get(path: str, params: dict) -> dict:
    url = f"{BYBIT_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    if data.get("retCode") != 0:
        raise BybitAPIError(data.get("retCode"), data.get("retMsg", "unknown"), path)
    return data["result"]


async def get_option_instruments(base_coin: str) -> list[dict]:
    """
    GET /v5/market/instruments-info?category=option&baseCoin=<BASE>

    Paginates via `cursor` until exhausted. Returns the raw `list` entries
    (one per option symbol: strike, type, deliveryTime, status, etc).
    """
    out: list[dict] = []
    cursor = ""
    while True:
        params = {"category": "option", "baseCoin": base_coin, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        result = await _get("/v5/market/instruments-info", params)
        out.extend(result.get("list", []))
        cursor = result.get("nextPageCursor") or ""
        if not cursor:
            break
    return out


async def get_option_tickers(base_coin: str) -> list[dict]:
    """
    GET /v5/market/tickers?category=option&baseCoin=<BASE>

    Returns the raw `list` entries: bid/ask, markPrice, markPriceIv, delta,
    gamma, vega, theta, openInterest, volume24h, underlyingPrice, etc.
    Not paginated by Bybit (single snapshot call).
    """
    result = await _get("/v5/market/tickers", {"category": "option", "baseCoin": base_coin})
    return result.get("list", [])
