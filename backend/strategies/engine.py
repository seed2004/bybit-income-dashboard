"""
Orchestrator: groups a chain by expiry and runs the requested strategy
generators against each expiry slice, then sorts the combined results.
"""
from __future__ import annotations

from backend.config import (
    DEFAULT_MAX_ABS_DELTA,
    DEFAULT_MIN_ABS_DELTA,
    DEFAULT_SPREAD_WIDTH_STRIKES,
)
from backend.models import OptionContract, StrategyCandidate
from backend.strategies import cash_secured_put, covered_call, credit_spread, iron_condor

STRATEGY_NAMES = [
    "cash_secured_put",
    "covered_call",
    "credit_spread",   # expands to bull_put_spread + bear_call_spread
    "iron_condor",      # expands to short_strangle + iron_condor
]


def run_strategies(
    contracts: list[OptionContract],
    strategies: list[str] | None = None,
    min_abs_delta: float = DEFAULT_MIN_ABS_DELTA,
    max_abs_delta: float = DEFAULT_MAX_ABS_DELTA,
    width_strikes: int = DEFAULT_SPREAD_WIDTH_STRIKES,
    sort_by: str = "annualized_yield_pct",
) -> list[StrategyCandidate]:
    strategies = strategies or STRATEGY_NAMES

    by_expiry: dict = {}
    for c in contracts:
        by_expiry.setdefault(c.expiry, []).append(c)

    results: list[StrategyCandidate] = []
    for _expiry, group in by_expiry.items():
        if "cash_secured_put" in strategies:
            results.extend(cash_secured_put.generate(group, min_abs_delta, max_abs_delta))
        if "covered_call" in strategies:
            results.extend(covered_call.generate(group, min_abs_delta, max_abs_delta))
        if "credit_spread" in strategies:
            results.extend(credit_spread.generate(group, min_abs_delta, max_abs_delta, width_strikes))
        if "iron_condor" in strategies:
            results.extend(iron_condor.generate(group, min_abs_delta, max_abs_delta, width_strikes))

    reverse = sort_by in ("annualized_yield_pct", "probability_of_profit", "net_credit")
    results.sort(
        key=lambda r: (-1 if (v := getattr(r, sort_by, None)) is None else v),
        reverse=reverse,
    )
    return results
