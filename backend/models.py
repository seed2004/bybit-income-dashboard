"""
Data models shared across the chain builder, strategy engine, and API layer.

Kept as plain dataclasses (not pydantic) for the internal pipeline so the
strategy math has zero framework overhead; pydantic is only used at the
FastAPI boundary (backend/app.py) to serialize responses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class OptionContract:
    """One option instrument merged with its live ticker snapshot."""

    symbol: str
    underlying: str          # BTC / ETH
    strike: float
    option_type: str         # "C" or "P"
    expiry: datetime         # UTC, from deliveryTime
    dte_days: float

    underlying_price: float  # spot/index price Bybit reports on the ticker
    bid: float
    ask: float
    mark_price: float
    mark_iv: float           # decimal, e.g. 0.55 = 55%
    delta: float
    gamma: float
    vega: float
    theta: float
    open_interest: float
    volume_24h: float

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2
        return self.mark_price

    @property
    def quoted_spread_pct(self) -> Optional[float]:
        if self.bid > 0 and self.ask > 0 and self.mid > 0:
            return (self.ask - self.bid) / self.mid
        return None

    @property
    def has_live_quote(self) -> bool:
        """True when Bybit is publishing an active bid/ask market for this contract."""
        return self.bid > 0 and self.ask > 0

    @property
    def is_illiquid(self) -> bool:
        from backend.config import MIN_OPEN_INTEREST, MAX_QUOTED_SPREAD_PCT

        if self.open_interest < MIN_OPEN_INTEREST:
            return True
        # Spread check only applies when a live quoted market exists.
        spread = self.quoted_spread_pct
        if spread is not None and spread > MAX_QUOTED_SPREAD_PCT:
            return True
        # No bid AND no mark price means truly no tradeable price.
        # bid=0 alone is normal for short-DTE options where Bybit reports
        # mark price but no live market-maker quote.
        if self.bid <= 0 and self.mark_price <= 0:
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "underlying": self.underlying,
            "strike": self.strike,
            "option_type": self.option_type,
            "expiry": self.expiry.isoformat(),
            "dte_days": round(self.dte_days, 2),
            "underlying_price": self.underlying_price,
            "bid": self.bid,
            "ask": self.ask,
            "mid": round(self.mid, 4),
            "mark_price": self.mark_price,
            "mark_iv": self.mark_iv,
            "delta": self.delta,
            "gamma": self.gamma,
            "vega": self.vega,
            "theta": self.theta,
            "open_interest": self.open_interest,
            "volume_24h": self.volume_24h,
            "quoted_spread_pct": self.quoted_spread_pct,
            "illiquid": self.is_illiquid,
            "has_live_quote": self.has_live_quote,
        }


@dataclass
class StrategyLeg:
    """One option leg of a strategy candidate, for display/audit."""

    symbol: str
    side: str        # "SELL" or "BUY"
    strike: float
    option_type: str
    price: float      # price used for this leg (mid, conservative-adjusted)
    delta: float
    mark_iv: float


@dataclass
class StrategyCandidate:
    """A ranked, ready-to-display trade idea."""

    strategy: str               # e.g. "cash_secured_put"
    underlying: str
    expiry: datetime
    dte_days: float
    legs: list[StrategyLeg] = field(default_factory=list)

    net_credit: float = 0.0     # premium received per 1 contract, in quote ccy
    collateral_or_margin: float = 0.0
    max_loss: float = 0.0       # for defined-risk strategies; None-ish (0) if undefined risk is flagged separately
    undefined_risk: bool = False

    breakevens: list[float] = field(default_factory=list)
    probability_of_profit: Optional[float] = None  # 0-1, Black-Scholes estimate at expiry

    annualized_yield_pct: float = 0.0
    underlying_price: float = 0.0

    illiquid: bool = False
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "underlying": self.underlying,
            "expiry": self.expiry.isoformat(),
            "dte_days": round(self.dte_days, 2),
            "legs": [
                {
                    "symbol": l.symbol,
                    "side": l.side,
                    "strike": l.strike,
                    "type": l.option_type,
                    "price": round(l.price, 4),
                    "delta": round(l.delta, 4),
                    "mark_iv": round(l.mark_iv, 4),
                }
                for l in self.legs
            ],
            "net_credit": round(self.net_credit, 4),
            "collateral_or_margin": round(self.collateral_or_margin, 4),
            "max_loss": round(self.max_loss, 4),
            "undefined_risk": self.undefined_risk,
            "breakevens": [round(b, 2) for b in self.breakevens],
            "probability_of_profit": (
                round(self.probability_of_profit, 4)
                if self.probability_of_profit is not None
                else None
            ),
            "annualized_yield_pct": round(self.annualized_yield_pct, 2),
            "underlying_price": round(self.underlying_price, 2),
            "illiquid": self.illiquid,
            "notes": self.notes,
        }


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
