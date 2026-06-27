"""
Synthetic but internally-consistent Bybit V5 option chain fixtures, used by
the offline test suite (tests/test_strategies.py).

WHY GENERATED, NOT RECORDED: the sandbox this project was built in cannot
reach api.bybit.com (network egress is allowlisted and Bybit isn't on it),
so a real recorded snapshot wasn't available while building this. Prices
here are produced with the same Black-Scholes formulas backend/strategies
uses, so the fixture is self-consistent (deltas, IV, and premiums actually
agree with each other) -- but it is NOT live market data. Before trusting
this tool's output for real trades, run it against the live API on a
machine with normal internet access and sanity-check a few quotes by eye
against the Bybit options UI.

Field names match the documented V5 schema:
  instruments-info (category=option): symbol, status, baseCoin, deliveryTime
  tickers (category=option): symbol, bidPrice, askPrice, markPrice,
    markPriceIv, underlyingPrice, delta, gamma, vega, theta, openInterest,
    volume24h
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_price_and_delta(S: float, K: float, T: float, sigma: float, option_type: str):
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if option_type == "C":
        price = S * _norm_cdf(d1) - K * _norm_cdf(d2)
        delta = _norm_cdf(d1)
    else:
        price = K * _norm_cdf(-d2) - S * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
    return max(price, 0.01), delta


def _fmt_expiry_token(dt: datetime) -> str:
    return f"{dt.day:02d}{dt.strftime('%b').upper()}{dt.strftime('%y')}"


def build_fixture(now: datetime, base_coin: str = "BTC", spot: float = 100_000.0):
    """Returns (instruments_list, tickers_list) for one underlying, with two
    short-dated expiries (3d and 6d out) and a strike ladder around spot."""
    instruments = []
    tickers = []

    expiries_days = [3, 6]
    # Strikes from -15% to +15% of spot in ~2% steps, rounded to nearest 500.
    pct_steps = [round(-0.15 + 0.02 * i, 2) for i in range(16)]
    strikes = sorted({round(spot * (1 + p) / 500) * 500 for p in pct_steps})

    for d in expiries_days:
        expiry_dt = (now + timedelta(days=d)).replace(hour=8, minute=0, second=0, microsecond=0)
        delivery_ms = str(int(expiry_dt.timestamp() * 1000))
        T = max((expiry_dt - now).total_seconds(), 1.0) / (365.0 * 86400.0)

        for strike in strikes:
            moneyness = (strike - spot) / spot
            sigma = 0.50 + 0.35 * abs(moneyness)  # simple smile

            for option_type in ("C", "P"):
                symbol = f"{base_coin}-{_fmt_expiry_token(expiry_dt)}-{strike}-{option_type}-USDT"

                instruments.append(
                    {
                        "symbol": symbol,
                        "status": "Trading",
                        "baseCoin": base_coin,
                        "quoteCoin": "USDT",
                        "settleCoin": "USDT",
                        "optionsType": "Call" if option_type == "C" else "Put",
                        "deliveryTime": delivery_ms,
                    }
                )

                price, delta = _bs_price_and_delta(spot, strike, T, sigma, option_type)
                # Thinner liquidity far from the money, mirroring real chains.
                distance = abs(moneyness)
                open_interest = max(5.0, 200.0 * math.exp(-8 * distance))
                volume_24h = max(0.0, 80.0 * math.exp(-10 * distance))
                spread_pct = 0.03 + 0.5 * distance  # wider spreads further OTM
                bid = round(price * (1 - spread_pct), 2)
                ask = round(price * (1 + spread_pct), 2)

                tickers.append(
                    {
                        "symbol": symbol,
                        "bidPrice": str(max(bid, 0.0)),
                        "bidSize": "10",
                        "bidIv": str(round(sigma, 4)),
                        "askPrice": str(ask),
                        "askSize": "10",
                        "askIv": str(round(sigma, 4)),
                        "lastPrice": str(round(price, 2)),
                        "highPrice24h": str(round(price * 1.1, 2)),
                        "lowPrice24h": str(round(price * 0.9, 2)),
                        "markPrice": str(round(price, 2)),
                        "indexPrice": str(spot),
                        "markPriceIv": str(round(sigma, 4)),
                        "underlyingPrice": str(spot),
                        "openInterest": str(round(open_interest, 2)),
                        "turnover24h": str(round(volume_24h * price, 2)),
                        "volume24h": str(round(volume_24h, 2)),
                        "totalVolume": str(round(volume_24h * 5, 2)),
                        "totalTurnover": str(round(volume_24h * price * 5, 2)),
                        "delta": str(round(delta, 6)),
                        "gamma": "0.00005",
                        "vega": "10.0",
                        "theta": str(round(-price / max(T * 365, 0.5), 4)),
                        "predictedDeliveryPrice": "0",
                        "change24h": "0",
                    }
                )

    return instruments, tickers


# An intentionally illiquid contract appended by tests that need one --
# kept here so the "shape" stays in one place.
def illiquid_ticker_overrides() -> dict:
    return {"bidPrice": "0", "bidSize": "0", "openInterest": "1"}
