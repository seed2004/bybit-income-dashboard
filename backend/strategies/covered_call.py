"""
Covered call: assumes you already hold the underlying (spot or perp) and
sell an OTM call against it. Yield is quoted against the current
underlying price (your effective cost basis isn't known by this tool, so
this is "yield if bought today" -- substitute your real cost basis when
comparing across your own holdings).

Risk note: this strategy caps upside above the strike but does NOT cap
downside -- if the underlying craters, the call premium only cushions a
small part of the loss. It is not "defined risk" in the way the credit
spreads below are.
"""
from __future__ import annotations

from backend.models import OptionContract, StrategyCandidate, StrategyLeg
from backend.strategies.common import (
    annualized_yield_pct,
    candidates_in_delta_band,
    dte_yield_note,
    prob_below,
    split_by_type,
)


def generate(
    contracts: list[OptionContract],
    min_abs_delta: float,
    max_abs_delta: float,
) -> list[StrategyCandidate]:
    if not contracts:
        return []

    calls, _puts = split_by_type(contracts)
    short_candidates = candidates_in_delta_band(calls, min_abs_delta, max_abs_delta)

    out: list[StrategyCandidate] = []
    for c in short_candidates:
        premium = c.mid
        if premium <= 0:
            continue
        breakeven = c.strike + premium  # upside breakeven for the call leg's own P&L
        T_years = max(c.dte_days, 0.0) / 365.0
        # Probability the call expires OTM (you keep the shares + full premium,
        # i.e. not called away). Does not capture downside risk on the shares.
        pop = prob_below(c.underlying_price, c.strike, T_years, c.mark_iv) if c.mark_iv > 0 else None

        out.append(
            StrategyCandidate(
                strategy="covered_call",
                underlying=c.underlying,
                expiry=c.expiry,
                dte_days=c.dte_days,
                legs=[
                    StrategyLeg(
                        symbol=c.symbol,
                        side="SELL",
                        strike=c.strike,
                        option_type="C",
                        price=premium,
                        delta=c.delta,
                        mark_iv=c.mark_iv,
                    )
                ],
                net_credit=premium,
                collateral_or_margin=c.underlying_price,  # 1 unit of underlying held
                max_loss=0.0,  # undefined; see undefined_risk flag
                undefined_risk=True,
                breakevens=[breakeven],
                probability_of_profit=pop,
                annualized_yield_pct=annualized_yield_pct(premium, c.underlying_price, c.dte_days),
                underlying_price=c.underlying_price,
                illiquid=c.is_illiquid,
                notes=(
                    "Requires holding 1 unit of underlying per contract. "
                    "POP = probability the call expires OTM (kept shares + premium); "
                    "does not account for losses on the underlying itself."
                    + dte_yield_note(c.dte_days)
                ),
            )
        )
    return out
