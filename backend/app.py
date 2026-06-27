"""
FastAPI app: serves the short-DTE option income dashboard.

Run with:
    uvicorn backend.app:app --reload --port 8000

Then open http://localhost:8000/ in a browser.

Scope reminder (see README "Roadmap"): this build is PUBLIC MARKET DATA
ONLY. No API keys are read, stored, or required. Order placement is not
implemented yet -- /api/suggestions returns trade *ideas* for you to
review and place yourself on Bybit, by design, until Phase 2.
"""
from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import chain
from backend.bybit_client import BybitAPIError
from backend.config import (
    DEFAULT_MAX_ABS_DELTA,
    DEFAULT_MAX_DTE,
    DEFAULT_MIN_ABS_DELTA,
    DEFAULT_MIN_DTE,
    DEFAULT_SPREAD_WIDTH_STRIKES,
    SUPPORTED_UNDERLYINGS,
)
from backend.strategies.engine import STRATEGY_NAMES, run_strategies

# ── Credential persistence helpers ────────────────────────────────────────────

_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")


def _load_dotenv(path: str) -> None:
    """Read KEY=VALUE pairs from a .env file into os.environ (existing env wins)."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k and k not in os.environ:
                os.environ[k] = v.strip()


def _write_env_key(path: str, key: str, value: str) -> None:
    """Upsert a single KEY=value line in the .env file."""
    lines: list[str] = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    found = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def _remove_env_key(path: str, key: str) -> None:
    """Remove a KEY line from the .env file if present."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(l for l in lines if not (l.startswith(f"{key}=") or l.startswith(f"{key} =")))


# Load persisted credentials into the process environment at startup.
_load_dotenv(_ENV_PATH)


class _CredentialsBody(BaseModel):
    api_key: str
    api_secret: str

app = FastAPI(title="Bybit Short-DTE Income Dashboard", version="0.1.0")

# allow_origins=["*"] is fine for a localhost-only tool; tighten this if
# the server is ever exposed on a network interface other than 127.0.0.1.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

# Fields that /api/suggestions accepts for sort_by.
# Descending fields: higher value = better rank.
# Ascending fields: lower value = better rank (shorter DTE, lower max loss).
_VALID_SORT_FIELDS: set[str] = {
    "annualized_yield_pct",
    "net_credit",
    "probability_of_profit",
    "dte_days",
    "max_loss",
}
_SORT_DESCENDING: set[str] = {"annualized_yield_pct", "net_credit", "probability_of_profit"}


def _parse_underlyings(raw: str) -> list[str]:
    requested = [u.strip().upper() for u in raw.split(",") if u.strip()]
    invalid = [u for u in requested if u not in SUPPORTED_UNDERLYINGS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported underlying(s): {invalid}. Supported: {SUPPORTED_UNDERLYINGS}",
        )
    return requested


@app.get("/api/health")
async def health():
    return {"status": "ok", "supported_underlyings": SUPPORTED_UNDERLYINGS}


@app.get("/api/ping-bybit")
async def ping_bybit():
    """Connectivity smoke-test: hits one small Bybit endpoint and returns the raw outcome."""
    import httpx
    url = "https://api.bybit.com/v5/market/time"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            return {"reachable": True, "status_code": r.status_code, "body": r.json()}
    except Exception as e:
        return {"reachable": False, "error_type": type(e).__name__, "error": str(e)}


@app.get("/api/meta")
async def meta():
    """Lets the frontend render filter dropdowns without hardcoding values."""
    return {
        "underlyings": SUPPORTED_UNDERLYINGS,
        "strategies": STRATEGY_NAMES,
        "sort_fields": sorted(_VALID_SORT_FIELDS),
        "defaults": {
            "min_dte": DEFAULT_MIN_DTE,
            "max_dte": DEFAULT_MAX_DTE,
            "min_abs_delta": DEFAULT_MIN_ABS_DELTA,
            "max_abs_delta": DEFAULT_MAX_ABS_DELTA,
            "width_strikes": DEFAULT_SPREAD_WIDTH_STRIKES,
        },
    }


@app.get("/api/chain")
async def get_chain(
    underlying: str = Query("BTC", description="Comma-separated, e.g. BTC,ETH"),
    min_dte: float = Query(DEFAULT_MIN_DTE),
    max_dte: float = Query(DEFAULT_MAX_DTE),
):
    underlyings = _parse_underlyings(underlying)
    try:
        chain_results = await asyncio.gather(
            *[chain.fetch_short_dte_chain(u, min_dte, max_dte) for u in underlyings]
        )
        out = [c.to_dict() for contracts in chain_results for c in contracts]
        return {"count": len(out), "contracts": out}
    except BybitAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach Bybit API: {type(e).__name__}: {e}")


@app.get("/api/suggestions")
async def get_suggestions(
    underlying: str = Query("BTC,ETH", description="Comma-separated, e.g. BTC,ETH"),
    strategies: str = Query(
        ",".join(STRATEGY_NAMES), description="Comma-separated subset of: " + ", ".join(STRATEGY_NAMES)
    ),
    min_dte: float = Query(DEFAULT_MIN_DTE),
    max_dte: float = Query(DEFAULT_MAX_DTE),
    min_abs_delta: float = Query(DEFAULT_MIN_ABS_DELTA),
    max_abs_delta: float = Query(DEFAULT_MAX_ABS_DELTA),
    width_strikes: int = Query(DEFAULT_SPREAD_WIDTH_STRIKES, ge=1, le=20),
    sort_by: str = Query("annualized_yield_pct"),
    limit: int = Query(50, ge=1, le=500),
    include_illiquid: bool = Query(False),
):
    underlyings = _parse_underlyings(underlying)
    requested_strategies = [s.strip() for s in strategies.split(",") if s.strip()]
    invalid_strats = [s for s in requested_strategies if s not in STRATEGY_NAMES]
    if invalid_strats:
        raise HTTPException(status_code=400, detail=f"Unknown strategy(ies): {invalid_strats}")

    if sort_by not in _VALID_SORT_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort_by '{sort_by}'. Valid options: {sorted(_VALID_SORT_FIELDS)}",
        )

    try:
        chain_results = await asyncio.gather(
            *[chain.fetch_short_dte_chain(u, min_dte, max_dte) for u in underlyings]
        )
    except BybitAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach Bybit API: {type(e).__name__}: {e}")

    all_candidates = []
    for contracts in chain_results:
        all_candidates.extend(
            run_strategies(
                contracts,
                strategies=requested_strategies,
                min_abs_delta=min_abs_delta,
                max_abs_delta=max_abs_delta,
                width_strikes=width_strikes,
            )
        )

    if not include_illiquid:
        all_candidates = [c for c in all_candidates if not c.illiquid]

    reverse = sort_by in _SORT_DESCENDING
    none_sentinel: float = -1 if reverse else float("inf")
    all_candidates.sort(
        key=lambda c: (none_sentinel if (v := getattr(c, sort_by, None)) is None else v),
        reverse=reverse,
    )

    return {
        "count": len(all_candidates[:limit]),
        "total_before_limit": len(all_candidates),
        "suggestions": [c.to_dict() for c in all_candidates[:limit]],
    }


# ── Credential endpoints ───────────────────────────────────────────────────────

@app.get("/api/settings/credentials")
async def get_credentials():
    """Returns whether API credentials are configured (never returns the actual secret)."""
    key = os.environ.get("BYBIT_API_KEY", "")
    configured = bool(key and os.environ.get("BYBIT_API_SECRET", ""))
    key_prefix = (key[:8] + "…") if len(key) >= 8 else (key or None)
    return {"configured": configured, "key_prefix": key_prefix if configured else None}


@app.post("/api/settings/credentials")
async def save_credentials(body: _CredentialsBody):
    """Save API key and secret to the local .env file and the running process environment."""
    if not body.api_key.strip() or not body.api_secret.strip():
        raise HTTPException(status_code=400, detail="api_key and api_secret must not be empty.")
    os.environ["BYBIT_API_KEY"] = body.api_key.strip()
    os.environ["BYBIT_API_SECRET"] = body.api_secret.strip()
    _write_env_key(_ENV_PATH, "BYBIT_API_KEY", body.api_key.strip())
    _write_env_key(_ENV_PATH, "BYBIT_API_SECRET", body.api_secret.strip())
    return {"saved": True}


@app.delete("/api/settings/credentials")
async def clear_credentials():
    """Remove API credentials from the running process and the .env file."""
    os.environ.pop("BYBIT_API_KEY", None)
    os.environ.pop("BYBIT_API_SECRET", None)
    _remove_env_key(_ENV_PATH, "BYBIT_API_KEY")
    _remove_env_key(_ENV_PATH, "BYBIT_API_SECRET")
    return {"cleared": True}


# --- Static dashboard -------------------------------------------------
app.mount("/static", StaticFiles(directory=_FRONTEND_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(_FRONTEND_DIR, "index.html"))
