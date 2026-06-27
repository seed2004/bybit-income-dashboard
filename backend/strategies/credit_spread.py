"""
Vertical credit spreads: defined-risk income trades.

- Bull put spread: sell a higher-strike put, buy a lower-strike put
  (further OTM) for protection. Profit if underlying stays above the
  short strike; max loss capped at spread width minus credit.
- Bear call spread: sell a lower-strike call, buy a higher-strike call
  for protection. Profit if underlying stays below the short strike.

Both are generated from the same delta-band short-leg selection used by
the naked strategies, then paired with a long wing `width_strikes` listed
strikes further OTM.
"""
from __future__ import annotations

from backend.models import OptionContract, StrategyCandidate, StrategyLeg
from backend.strategies.common import (
    annualized_yield_pct,
    candidates_in_delta_band,
    dte_yield_note,
    find_wing,
    prob_above,
    prob_below,
    split_by_type,
)


def _build_candidate(
    short: OptionContract,
    long: OptionContract,
    strategy_name: str,
    notes: str,
) -> StrategyCandidate | None:
    short_premium = short.mid
    long_premium = long.mid
    if short_premium <= 0:
        return None
    # Paying the ask of the long (protective) leg and receiving the bid of
    # the short leg would be the conservative, fillable-price version; mid
    # prices are used here for a representative estimate.
    net_credit = short_premium - long_premium
    if net_credit <= 0:
        return None  # not a credit spread at these mid prices, skip

    width = abs(long.strike - short.strike)
    max_loss = max(width - net_credit, 0.0)
    T_years = max(short.dte_days, 0.0) / 365.0
    sigma = short.mark_iv  # IV of the short leg drives the breakeven probability

    if short.option_type == "P":
        breakeven = short.strike - net_credit
        pop = prob_above(short.underlying_price, breakeven, T_years, sigma) if sigma > 0 else None
        legs = [
            StrategyLeg(short.symbol, "SELL", short.strike, "P", short_premium, short.delta, short.mark_iv),
            StrategyLeg(long.symbol, "BUY", long.strike, "P", long_premium, long.delta, long.mark_iv),
        ]
    else:
        breakeven = short.strike + net_credit
        pop = prob_below(short.underlying_price, breakeven, T_years, sigma) if sigma > 0 else None
        legs = [
            StrategyLeg(short.symbol, "SELL", short.strike, "C", short_premium, short.delta, short.mark_iv),
            StrategyLeg(long.symbol, "BUY", long.strike, "C", long_premium, long.delta, long.mark_iv),
        ]

    return StrategyCandidate(
        strategy=strategy_name,
        underlying=short.underlying,
        expiry=short.expiry,
        dte_days=short.dte_days,
        legs=legs,
        net_credit=net_credit,
        collateral_or_margin=max_loss,
        max_loss=max_loss,
        undefined_risk=False,
        breakevens=[breakeven],
        probability_of_profit=pop,
        annualized_yield_pct=annualized_yield_pct(net_credit, max_loss, short.dte_days),
        underlying_price=short.underlying_price,
        illiquid=short.is_illiquid or long.is_illiquid,
        notes=notes + dte_yield_note(short.dte_days),
    )


def generate(
    contracts: list[OptionContract],
    min_abs_delta: float,
    max_abs_delta: float,
    width_strikes: int,
) -> list[StrategyCandidate]:
    if not contracts:
        return []

    calls, puts = split_by_type(contracts)
    out: list[StrategyCandidate] = []

    for short_put in candidates_in_delta_band(puts, min_abs_delta, max_abs_delta):
        long_put = find_wing(puts, short_put, width_strikes)
        if long_put is None:
            continue
        cand = _build_candidate(
            short_put,
            long_put,
            "bull_put_spread",
            "Defined-risk: sell higher put, buy lower put. Max loss capped at width - credit.",
        )
        if cand:
            out.append(cand)

    for short_call in candidates_in_delta_band(calls, min_abs_delta, max_abs_delta):
        long_call = find_wing(calls, short_call, width_strikes)
        if long_call is None:
            continue
        cand = _build_candidate(
            short_call,
            long_call,
            "bear_call_spread",
            "Defined-risk: sell lower call, buy higher call. Max loss capped at width - credit.",
        )
        if cand:
            out.append(cand)

    return out
