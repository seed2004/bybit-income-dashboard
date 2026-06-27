"""
Shared math + selection helpers for every strategy module.

Probability-of-profit is estimated with the standard Black-Scholes
lognormal assumption: given spot/index price S, a strike (or breakeven) K,
time to expiry T (years), and the option's mark IV (sigma), the
risk-neutral probability that S_T ends up above/below K is N(d2)/N(-d2).

This is a model estimate, not a guarantee -- it assumes IV is an unbiased
forecast of realized volatility and that returns are lognormal, both of
which are simplifications for crypto. Treat it as a ranking signal, not a
promise.
"""
from __future__ import annotations

import math
from typing import Optional

from backend.config import RISK_FREE_RATE
from backend.models import OptionContract


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _d2(S: float, K: float, T: float, sigma: float, r: float = RISK_FREE_RATE) -> Optional[float]:
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return None
    return (math.log(S / K) + (r - 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))


def prob_above(S: float, K: float, T: float, sigma: float) -> Optional[float]:
    """P(S_T > K) at expiry under lognormal/BS assumptions."""
    d2 = _d2(S, K, T, sigma)
    if d2 is None:
        return None
    return norm_cdf(d2)


def prob_below(S: float, K: float, T: float, sigma: float) -> Optional[float]:
    d2 = _d2(S, K, T, sigma)
    if d2 is None:
        return None
    return norm_cdf(-d2)


def prob_in_range(S: float, k_low: float, k_high: float, T: float, sigma: float) -> Optional[float]:
    """P(k_low < S_T < k_high) at expiry."""
    p_below_high = prob_below(S, k_high, T, sigma)
    p_below_low = prob_below(S, k_low, T, sigma)
    if p_below_high is None or p_below_low is None:
        return None
    return max(0.0, p_below_high - p_below_low)


def annualized_yield_pct(premium: float, basis: float, dte_days: float) -> float:
    """premium / capital-at-risk, annualized. dte_days is floored at 6h so
    0-DTE trades don't produce nonsensical (or divide-by-zero) numbers --
    the floor only affects this ratio, never the displayed DTE itself."""
    if basis <= 0:
        return 0.0
    dte_floor = max(dte_days, 0.25)
    return (premium / basis) * (365.0 / dte_floor) * 100.0


def dte_yield_note(dte_days: float) -> str:
    """Returns a warning suffix when DTE is < 6 hours; annualized yield is
    misleading at that time scale — the raw premium is more informative."""
    if dte_days < 0.25:
        return " 0-DTE: annualized yield is not meaningful — compare raw premium instead."
    return ""


def split_by_type(contracts: list[OptionContract]) -> tuple[list[OptionContract], list[OptionContract]]:
    """Returns (calls, puts), each sorted by strike ascending."""
    calls = sorted((c for c in contracts if c.option_type == "C"), key=lambda c: c.strike)
    puts = sorted((c for c in contracts if c.option_type == "P"), key=lambda c: c.strike)
    return calls, puts


def candidates_in_delta_band(
    contracts: list[OptionContract], min_abs_delta: float, max_abs_delta: float
) -> list[OptionContract]:
    return [c for c in contracts if min_abs_delta <= abs(c.delta) <= max_abs_delta]


def find_wing(
    sorted_contracts: list[OptionContract], short: OptionContract, width_strikes: int
) -> Optional[OptionContract]:
    """Find the long (protective) leg `width_strikes` listed strikes away
    from `short`, in the OTM direction for that option type:
      - puts: further OTM means a LOWER strike (downside protection)
      - calls: further OTM means a HIGHER strike (upside protection)
    Returns None if there aren't enough listed strikes in that direction.
    """
    try:
        idx = next(i for i, c in enumerate(sorted_contracts) if c.symbol == short.symbol)
    except StopIteration:
        return None

    if short.option_type == "P":
        target = idx - width_strikes
    else:
        target = idx + width_strikes

    if target < 0 or target >= len(sorted_contracts):
        return None
    return sorted_contracts[target]
