"""
Offline test suite -- runs entirely on synthetic fixture data
(tests/fixtures/sample_data.py), no network access required.

Run from the project root:
    python -m unittest tests.test_strategies -v

This is intentionally network-free: the dev sandbox this project was built
in blocks egress to api.bybit.com, so these tests validate the *parsing
and strategy math* against a self-consistent synthetic chain. They do NOT
prove the live Bybit integration works end-to-end -- see README "Before
you trust this with real money" for the live smoke-test step you should
run once on a machine with normal internet access.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import backend.chain as chain_module
from backend import chain
from backend.chain import parse_symbol
from backend.models import OptionContract
from backend.strategies import common
from backend.strategies.engine import run_strategies
from tests.fixtures.sample_data import build_fixture, illiquid_ticker_overrides

NOW = datetime.now(timezone.utc)
INSTRUMENTS, TICKERS = build_fixture(NOW, base_coin="BTC", spot=100_000.0)


async def _fetch_test_chain(min_dte=0, max_dte=7):
    with patch("backend.chain.bybit_client.get_option_instruments", new=AsyncMock(return_value=INSTRUMENTS)), \
         patch("backend.chain.bybit_client.get_option_tickers", new=AsyncMock(return_value=TICKERS)):
        return await chain.fetch_short_dte_chain("BTC", min_dte=min_dte, max_dte=max_dte)


class TestSymbolParsing(unittest.TestCase):
    def test_parses_call(self):
        self.assertEqual(parse_symbol("BTC-27JUN26-100000-C"), ("BTC", 100000.0, "C"))

    def test_parses_put(self):
        self.assertEqual(parse_symbol("ETH-03JUL26-3500-P"), ("ETH", 3500.0, "P"))

    def test_parses_decimal_strike(self):
        self.assertEqual(parse_symbol("BTC-27JUN26-0.5-C"), ("BTC", 0.5, "C"))

    def test_parses_usdt_suffix(self):
        # Bybit appends -USDT to option symbols in the current API
        self.assertEqual(parse_symbol("BTC-27JUN26-100000-C-USDT"), ("BTC", 100000.0, "C"))
        self.assertEqual(parse_symbol("ETH-03JUL26-3500-P-USDC"), ("ETH", 3500.0, "P"))

    def test_rejects_garbage(self):
        self.assertIsNone(parse_symbol("not-an-option-symbol"))


class TestProbabilityMath(unittest.TestCase):
    def test_prob_above_and_below_sum_to_one(self):
        p_above = common.prob_above(100_000, 100_000, 5 / 365, 0.55)
        p_below = common.prob_below(100_000, 100_000, 5 / 365, 0.55)
        self.assertAlmostEqual(p_above + p_below, 1.0, places=9)

    def test_otm_put_breakeven_has_high_pop(self):
        # Breakeven far below spot -> high probability spot stays above it.
        pop = common.prob_above(100_000, 80_000, 5 / 365, 0.55)
        self.assertGreater(pop, 0.85)

    def test_prob_in_range_matches_manual_difference(self):
        S, T, sigma = 100_000, 5 / 365, 0.55
        lo, hi = 90_000, 110_000
        manual = common.prob_below(S, hi, T, sigma) - common.prob_below(S, lo, T, sigma)
        self.assertAlmostEqual(common.prob_in_range(S, lo, hi, T, sigma), manual, places=9)

    def test_annualized_yield_basic(self):
        # $100 premium on $10,000 collateral, 5 DTE -> simple sanity check on scale.
        y = common.annualized_yield_pct(premium=100, basis=10_000, dte_days=5)
        expected = (100 / 10_000) * (365 / 5) * 100
        self.assertAlmostEqual(y, expected, places=6)

    def test_annualized_yield_zero_basis_safe(self):
        self.assertEqual(common.annualized_yield_pct(premium=10, basis=0, dte_days=5), 0.0)

    def test_dte_yield_note_triggers_below_quarter_day(self):
        self.assertNotEqual(common.dte_yield_note(0.1), "")
        self.assertNotEqual(common.dte_yield_note(0.0), "")

    def test_dte_yield_note_empty_above_quarter_day(self):
        self.assertEqual(common.dte_yield_note(0.25), "")
        self.assertEqual(common.dte_yield_note(1.0), "")
        self.assertEqual(common.dte_yield_note(7.0), "")


class TestLiquidityFlag(unittest.TestCase):
    """Tests for OptionContract.is_illiquid using the illiquid_ticker_overrides fixture."""

    def _make_contract(self, bid: float, ask: float, open_interest: float) -> OptionContract:
        return OptionContract(
            symbol="BTC-01JAN27-100000-C",
            underlying="BTC",
            strike=100_000,
            option_type="C",
            expiry=datetime(2027, 1, 1, tzinfo=timezone.utc),
            dte_days=5,
            underlying_price=100_000,
            bid=bid,
            ask=ask,
            mark_price=500,
            mark_iv=0.5,
            delta=0.2,
            gamma=0.001,
            vega=10.0,
            theta=-5.0,
            open_interest=open_interest,
            volume_24h=10.0,
        )

    def test_zero_bid_zero_mark_is_illiquid(self):
        # bid=0 + mark_price=0 → truly no tradeable price
        c = self._make_contract(bid=0, ask=0, open_interest=10)
        c.mark_price = 0
        self.assertTrue(c.is_illiquid)

    def test_zero_bid_with_mark_price_not_illiquid(self):
        # bid=0 but mark_price > 0 → Bybit mark-price-only quote, still tradeable
        c = self._make_contract(bid=0, ask=0, open_interest=10)
        # mark_price is set to 500 in _make_contract; confirm not flagged illiquid
        self.assertFalse(c.is_illiquid)

    def test_low_open_interest_is_illiquid(self):
        overrides = illiquid_ticker_overrides()
        c = self._make_contract(bid=10, ask=11, open_interest=float(overrides["openInterest"]))
        self.assertTrue(c.is_illiquid)

    def test_wide_spread_is_illiquid(self):
        # (ask - bid) / mid = (100 - 1) / 50.5 ≈ 1.96 >> 0.40
        c = self._make_contract(bid=1, ask=100, open_interest=10)
        self.assertTrue(c.is_illiquid)

    def test_liquid_contract_not_flagged(self):
        # bid/ask tight, OI above threshold
        c = self._make_contract(bid=99, ask=101, open_interest=10)
        self.assertFalse(c.is_illiquid)


class TestChainBuilding(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        chain_module._chain_cache.clear()

    async def test_chain_nonempty_and_within_dte_window(self):
        contracts = await _fetch_test_chain(0, 7)
        self.assertGreater(len(contracts), 0)
        for c in contracts:
            self.assertGreaterEqual(c.dte_days, 0)
            self.assertLessEqual(c.dte_days, 7)
            self.assertIn(c.option_type, ("C", "P"))
            self.assertEqual(c.underlying, "BTC")

    async def test_dte_window_excludes_outside_range(self):
        # Fixture only has 3d/6d expiries -- a 0-2 day window should be empty.
        contracts = await _fetch_test_chain(0, 2)
        self.assertEqual(len(contracts), 0)

    async def test_mid_price_uses_bid_ask_when_available(self):
        contracts = await _fetch_test_chain(0, 7)
        priced = [c for c in contracts if c.bid > 0 and c.ask > 0]
        self.assertTrue(priced)
        for c in priced[:5]:
            self.assertAlmostEqual(c.mid, (c.bid + c.ask) / 2, places=6)

    async def test_chain_cache_returns_same_object_on_second_call(self):
        first = await _fetch_test_chain(0, 7)
        # Second call should hit the cache; patch is still active so data is consistent.
        second = await _fetch_test_chain(0, 7)
        self.assertEqual(len(first), len(second))
        self.assertEqual(first[0].symbol, second[0].symbol)


class TestStrategyEngine(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        chain_module._chain_cache.clear()
        self.contracts = await _fetch_test_chain(0, 7)

    def test_cash_secured_put_candidates_well_formed(self):
        results = run_strategies(self.contracts, strategies=["cash_secured_put"])
        self.assertTrue(results, "expected at least one cash-secured put candidate")
        for r in results:
            self.assertEqual(r.strategy, "cash_secured_put")
            self.assertEqual(len(r.legs), 1)
            self.assertEqual(r.legs[0].side, "SELL")
            self.assertFalse(r.undefined_risk)
            self.assertEqual(len(r.breakevens), 1)
            self.assertTrue(0.10 - 1e-9 <= abs(r.legs[0].delta) <= 0.35 + 1e-9)
            if r.probability_of_profit is not None:
                self.assertTrue(0.0 <= r.probability_of_profit <= 1.0)
            self.assertGreater(r.annualized_yield_pct, 0)

    def test_covered_call_candidates_flagged_undefined_risk(self):
        results = run_strategies(self.contracts, strategies=["covered_call"])
        self.assertTrue(results, "expected at least one covered call candidate")
        for r in results:
            self.assertEqual(r.strategy, "covered_call")
            self.assertTrue(r.undefined_risk)
            self.assertEqual(r.legs[0].option_type, "C")

    def test_credit_spreads_both_directions_present_and_capped(self):
        results = run_strategies(self.contracts, strategies=["credit_spread"], width_strikes=2)
        names = {r.strategy for r in results}
        self.assertIn("bull_put_spread", names)
        self.assertIn("bear_call_spread", names)
        for r in results:
            self.assertEqual(len(r.legs), 2)
            self.assertFalse(r.undefined_risk)
            width = abs(r.legs[0].strike - r.legs[1].strike)
            self.assertAlmostEqual(r.max_loss, max(width - r.net_credit, 0.0), places=4)
            self.assertGreaterEqual(r.max_loss, 0)
            self.assertGreater(r.net_credit, 0)

    def test_credit_spreads_width_strikes_1(self):
        results = run_strategies(self.contracts, strategies=["credit_spread"], width_strikes=1)
        self.assertTrue(results, "width_strikes=1 should still produce candidates")
        for r in results:
            self.assertGreater(r.net_credit, 0)

    def test_credit_spreads_width_strikes_20(self):
        # Very wide wings — may produce candidates if the fixture chain is deep enough.
        results = run_strategies(self.contracts, strategies=["credit_spread"], width_strikes=20)
        # Just verify none have negative net_credit if they exist.
        for r in results:
            self.assertGreater(r.net_credit, 0)

    def test_iron_condor_and_strangle_present(self):
        results = run_strategies(self.contracts, strategies=["iron_condor"], width_strikes=2)
        names = {r.strategy for r in results}
        self.assertIn("short_strangle", names)
        self.assertIn("iron_condor", names)

        condors = [r for r in results if r.strategy == "iron_condor"]
        for r in condors:
            self.assertEqual(len(r.legs), 4)
            self.assertFalse(r.undefined_risk)
            self.assertEqual(len(r.breakevens), 2)
            self.assertLess(r.breakevens[0], r.breakevens[1])

        strangles = [r for r in results if r.strategy == "short_strangle"]
        for r in strangles:
            self.assertEqual(len(r.legs), 2)
            self.assertTrue(r.undefined_risk)

    def test_results_sorted_by_annualized_yield_desc_by_default(self):
        results = run_strategies(self.contracts, strategies=["cash_secured_put"])
        yields = [r.annualized_yield_pct for r in results]
        self.assertEqual(yields, sorted(yields, reverse=True))

    def test_empty_contracts_returns_empty(self):
        for strategy in ("cash_secured_put", "covered_call", "credit_spread", "iron_condor"):
            results = run_strategies([], strategies=[strategy])
            self.assertEqual(results, [], f"{strategy} should return [] for empty contracts")

    def test_tight_delta_band_may_yield_zero_candidates(self):
        # An impossible delta range should produce no candidates, not an error.
        results = run_strategies(
            self.contracts,
            strategies=["cash_secured_put"],
            min_abs_delta=0.5,
            max_abs_delta=0.5,
        )
        # Either zero or some — just must not raise.
        self.assertIsInstance(results, list)


if __name__ == "__main__":
    unittest.main()
