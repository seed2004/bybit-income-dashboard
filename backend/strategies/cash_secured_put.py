"""
Cash-secured short put: sell an OTM put, reserve `strike` in stablecoin as
collateral. Income = premium. Worst case = assigned and underlying goes to
zero (max_loss reported as strike - premium, the textbook worst case).
"""
from __future__ import annotations

from backend.models import OptionContract, StrategyCandidate, StrategyLeg
from backend.strategies.common import (
    annualized_yield_pct,
    candidates_in_delta_band,
    dte_yield_note,
    prob_above,
    split_by_type,
)


def generate(
    contracts: list[OptionContract],
    min_abs_delta: float,
    max_abs_delta: float,
) -> list[StrategyCandidate]:
    """`contracts` should already be filtered to one underlying + one expiry."""
    if not contracts:
        return []

    _calls, puts = split_by_type(contracts)
    short_candidates = candidates_in_delta_band(puts, min_abs_delta, max_abs_delta)

    out: list[StrategyCandidate] = []
    for c in short_candidates:
        premium = c.mid
        if premium <= 0:
            continue
        collateral = c.strike
        breakeven = c.strike - premium
        T_years = max(c.dte_days, 0.0) / 365.0
        pop = prob_above(c.underlying_price, breakeven, T_years, c.mark_iv) if c.mark_iv > 0 else None

        out.append(
            StrategyCandidate(
                strategy="cash_secured_put",
                underlying=c.underlying,
                expiry=c.expiry,
                dte_days=c.dte_days,
                legs=[
                    StrategyLeg(
                        symbol=c.symbol,
                        side="SELL",
                        strike=c.strike,
                        option_type="P",
                        price=premium,
                        delta=c.delta,
                        mark_iv=c.mark_iv,
                    )
                ],
                net_credit=premium,
                collateral_or_margin=collateral,
                max_loss=max(collateral - premium, 0.0),
                undefined_risk=False,
                breakevens=[breakeven],
                probability_of_profit=pop,
                annualized_yield_pct=annualized_yield_pct(premium, collateral, c.dte_days),
                underlying_price=c.underlying_price,
                illiquid=c.is_illiquid,
                notes=(
                    "Naked short put, fully cash-collateralized. Worst case: assigned, underlying -> $0."
                    + dte_yield_note(c.dte_days)
                ),
            )
        )
    return out
