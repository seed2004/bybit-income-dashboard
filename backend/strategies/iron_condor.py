"""
Two-sided premium-selling strategies on the same expiry:

- Short strangle: sell an OTM put + an OTM call, no wings. Higher credit,
  undefined risk (the call side in particular has theoretical unlimited
  loss if underlying rips higher).
- Iron condor: the same put+call combo, but each side has a protective
  wing `width_strikes` further OTM, making risk defined on both sides.

Both profit if the underlying stays between the two breakevens through
expiry -- the classic "range-bound, collect theta" structure.
"""
from __future__ import annotations

from backend.models import OptionContract, StrategyCandidate, StrategyLeg
from backend.strategies.common import (
    annualized_yield_pct,
    candidates_in_delta_band,
    dte_yield_note,
    find_wing,
    prob_in_range,
    split_by_type,
)


def _avg_iv(*contracts: OptionContract) -> float:
    ivs = [c.mark_iv for c in contracts if c.mark_iv > 0]
    return sum(ivs) / len(ivs) if ivs else 0.0


def _short_strangle_candidate(short_put: OptionContract, short_call: OptionContract) -> StrategyCandidate | None:
    put_premium, call_premium = short_put.mid, short_call.mid
    if put_premium <= 0 or call_premium <= 0:
        return None
    total_credit = put_premium + call_premium
    lower_be = short_put.strike - total_credit
    upper_be = short_call.strike + total_credit
    T_years = max(short_put.dte_days, 0.0) / 365.0
    sigma = _avg_iv(short_put, short_call)
    pop = prob_in_range(short_put.underlying_price, lower_be, upper_be, T_years, sigma) if sigma > 0 else None

    return StrategyCandidate(
        strategy="short_strangle",
        underlying=short_put.underlying,
        expiry=short_put.expiry,
        dte_days=short_put.dte_days,
        legs=[
            StrategyLeg(short_put.symbol, "SELL", short_put.strike, "P", put_premium, short_put.delta, short_put.mark_iv),
            StrategyLeg(short_call.symbol, "SELL", short_call.strike, "C", call_premium, short_call.delta, short_call.mark_iv),
        ],
        net_credit=total_credit,
        collateral_or_margin=short_put.strike,  # approx: put side notional dominates typical exchange margin
        max_loss=0.0,
        undefined_risk=True,
        breakevens=[lower_be, upper_be],
        probability_of_profit=pop,
        annualized_yield_pct=annualized_yield_pct(total_credit, short_put.strike, short_put.dte_days),
        underlying_price=short_put.underlying_price,
        illiquid=short_put.is_illiquid or short_call.is_illiquid,
        notes=(
            "Naked both sides. Call side has theoretically unlimited loss; put side capped at strike -> $0."
            + dte_yield_note(short_put.dte_days)
        ),
    )


def _iron_condor_candidate(
    short_put: OptionContract,
    long_put: OptionContract,
    short_call: OptionContract,
    long_call: OptionContract,
) -> StrategyCandidate | None:
    put_credit = short_put.mid - long_put.mid
    call_credit = short_call.mid - long_call.mid
    if put_credit <= 0 or call_credit <= 0:
        return None
    total_credit = put_credit + call_credit
    put_width = short_put.strike - long_put.strike
    call_width = long_call.strike - short_call.strike
    # Only one side can finish ITM at expiry, so margin/max-loss is the
    # worse single side, net of the *total* credit collected from both.
    max_loss = max(max(put_width, call_width) - total_credit, 0.0)

    lower_be = short_put.strike - total_credit
    upper_be = short_call.strike + total_credit
    T_years = max(short_put.dte_days, 0.0) / 365.0
    sigma = _avg_iv(short_put, short_call)
    pop = prob_in_range(short_put.underlying_price, lower_be, upper_be, T_years, sigma) if sigma > 0 else None

    return StrategyCandidate(
        strategy="iron_condor",
        underlying=short_put.underlying,
        expiry=short_put.expiry,
        dte_days=short_put.dte_days,
        legs=[
            StrategyLeg(short_put.symbol, "SELL", short_put.strike, "P", short_put.mid, short_put.delta, short_put.mark_iv),
            StrategyLeg(long_put.symbol, "BUY", long_put.strike, "P", long_put.mid, long_put.delta, long_put.mark_iv),
            StrategyLeg(short_call.symbol, "SELL", short_call.strike, "C", short_call.mid, short_call.delta, short_call.mark_iv),
            StrategyLeg(long_call.symbol, "BUY", long_call.strike, "C", long_call.mid, long_call.delta, long_call.mark_iv),
        ],
        net_credit=total_credit,
        collateral_or_margin=max_loss,
        max_loss=max_loss,
        undefined_risk=False,
        breakevens=[lower_be, upper_be],
        probability_of_profit=pop,
        annualized_yield_pct=annualized_yield_pct(total_credit, max_loss, short_put.dte_days),
        underlying_price=short_put.underlying_price,
        illiquid=any(c.is_illiquid for c in (short_put, long_put, short_call, long_call)),
        notes=(
            "Defined risk both sides. Max loss = worse wing width - total credit (approx; "
            "live margin may differ if both wings are challenged simultaneously before expiry)."
            + dte_yield_note(short_put.dte_days)
        ),
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
    short_puts = candidates_in_delta_band(puts, min_abs_delta, max_abs_delta)
    short_calls = candidates_in_delta_band(calls, min_abs_delta, max_abs_delta)

    # Precompute protective wings once per short leg (find_wing is O(n) per call).
    # Computing inside the double loop was O(puts * calls * n); now it's O((puts + calls) * n).
    lp_by_symbol = {sp.symbol: find_wing(puts, sp, width_strikes) for sp in short_puts}
    lc_by_symbol = {sc.symbol: find_wing(calls, sc, width_strikes) for sc in short_calls}

    out: list[StrategyCandidate] = []
    for sp in short_puts:
        lp = lp_by_symbol[sp.symbol]
        for sc in short_calls:
            strangle = _short_strangle_candidate(sp, sc)
            if strangle:
                out.append(strangle)

            lc = lc_by_symbol[sc.symbol]
            if lp is not None and lc is not None:
                condor = _iron_condor_candidate(sp, lp, sc, lc)
                if condor:
                    out.append(condor)

    return out
