"""
Builds a normalized, short-DTE-filtered option chain by merging
instruments-info (contract specs: strike, type, expiry, status) with
tickers (live pricing: bid/ask, mark, IV, greeks, OI, volume).
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Optional

from backend import bybit_client
from backend.config import DEFAULT_MAX_DTE, DEFAULT_MIN_DTE
from backend.models import OptionContract

# Per-underlying TTL cache so repeated dashboard refreshes don't hammer Bybit.
_chain_cache: dict[str, tuple[float, list[OptionContract]]] = {}
_CACHE_TTL = 30.0  # seconds

# Bybit option symbols: "BTC-27JUN26-100000-C" (legacy) or "BTC-27JUN26-100000-C-USDT" (current)
_SYMBOL_RE = re.compile(r"^([A-Z]+)-(\d{1,2}[A-Z]{3}\d{2})-(\d+(?:\.\d+)?)-([CP])(?:-[A-Z]+)?$")


def parse_symbol(symbol: str) -> Optional[tuple[str, float, str]]:
    """Returns (underlying, strike, option_type) parsed straight from the
    instrument symbol. This is the authoritative source for strike/type
    since it's guaranteed present on every contract Bybit lists."""
    m = _SYMBOL_RE.match(symbol)
    if not m:
        return None
    underlying, _expiry_token, strike_str, opt_type = m.groups()
    return underlying, float(strike_str), opt_type


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


async def fetch_chain(base_coin: str) -> list[OptionContract]:
    """Fetch + merge instruments and tickers for one underlying. No DTE
    filtering here -- callers decide the window (default applied by
    `fetch_short_dte_chain` below). Results are cached for _CACHE_TTL seconds."""
    now_mono = time.monotonic()
    cached = _chain_cache.get(base_coin)
    if cached is not None:
        ts, data = cached
        if now_mono - ts < _CACHE_TTL:
            return data

    instruments = await bybit_client.get_option_instruments(base_coin)
    tickers = await bybit_client.get_option_tickers(base_coin)
    ticker_by_symbol = {t["symbol"]: t for t in tickers}

    now = datetime.now(timezone.utc)
    contracts: list[OptionContract] = []

    for inst in instruments:
        if inst.get("status") != "Trading":
            continue
        symbol = inst["symbol"]
        ticker = ticker_by_symbol.get(symbol)
        if ticker is None:
            # Listed but no live quote snapshot (can happen right after
            # listing or for very illiquid far-dated strikes) -- skip.
            continue

        parsed = parse_symbol(symbol)
        if parsed is None:
            continue
        underlying, strike, option_type = parsed

        delivery_ms = _safe_float(inst.get("deliveryTime"))
        if delivery_ms <= 0:
            continue
        expiry = datetime.fromtimestamp(delivery_ms / 1000, tz=timezone.utc)
        dte_days = (expiry - now).total_seconds() / 86400.0
        if dte_days < 0:
            continue  # already expired, stale instrument entry

        contracts.append(
            OptionContract(
                symbol=symbol,
                underlying=underlying,
                strike=strike,
                option_type=option_type,
                expiry=expiry,
                dte_days=dte_days,
                underlying_price=_safe_float(ticker.get("underlyingPrice")),
                bid=_safe_float(ticker.get("bidPrice")),
                ask=_safe_float(ticker.get("askPrice")),
                mark_price=_safe_float(ticker.get("markPrice")),
                mark_iv=_safe_float(ticker.get("markPriceIv") or ticker.get("markIv")),
                delta=_safe_float(ticker.get("delta")),
                gamma=_safe_float(ticker.get("gamma")),
                vega=_safe_float(ticker.get("vega")),
                theta=_safe_float(ticker.get("theta")),
                open_interest=_safe_float(ticker.get("openInterest")),
                volume_24h=_safe_float(ticker.get("volume24h")),
            )
        )

    _chain_cache[base_coin] = (now_mono, contracts)
    return contracts


def filter_by_dte(
    contracts: list[OptionContract],
    min_dte: float = DEFAULT_MIN_DTE,
    max_dte: float = DEFAULT_MAX_DTE,
) -> list[OptionContract]:
    return [c for c in contracts if min_dte <= c.dte_days <= max_dte]


async def fetch_short_dte_chain(
    base_coin: str,
    min_dte: float = DEFAULT_MIN_DTE,
    max_dte: float = DEFAULT_MAX_DTE,
) -> list[OptionContract]:
    contracts = await fetch_chain(base_coin)
    return filter_by_dte(contracts, min_dte, max_dte)


def group_by_expiry(contracts: list[OptionContract]) -> dict[datetime, list[OptionContract]]:
    grouped: dict[datetime, list[OptionContract]] = {}
    for c in contracts:
        grouped.setdefault(c.expiry, []).append(c)
    return grouped
