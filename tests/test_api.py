"""
In-process API smoke test using FastAPI's TestClient (no real network
needed) -- patches the Bybit client the same way test_strategies.py does,
so this exercises the actual HTTP routes, query-param parsing, and JSON
serialization end-to-end, just not the real Bybit connection.

Run from the project root:
    python -m unittest tests.test_api -v
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import backend.chain as chain_module
from backend.app import app
from tests.fixtures.sample_data import build_fixture

NOW = datetime.now(timezone.utc)
INSTRUMENTS, TICKERS = build_fixture(NOW, base_coin="BTC", spot=100_000.0)
ETH_INSTRUMENTS, ETH_TICKERS = build_fixture(NOW, base_coin="ETH", spot=3_500.0)


def _fake_instruments(base_coin: str):
    return {"BTC": INSTRUMENTS, "ETH": ETH_INSTRUMENTS}.get(base_coin, [])


def _fake_tickers(base_coin: str):
    return {"BTC": TICKERS, "ETH": ETH_TICKERS}.get(base_coin, [])


class TestAPI(unittest.TestCase):
    def setUp(self):
        # Clear the chain cache so each test fetches fresh (mocked) data.
        chain_module._chain_cache.clear()
        self.client = TestClient(app)
        self.patches = [
            patch(
                "backend.chain.bybit_client.get_option_instruments",
                new=AsyncMock(side_effect=_fake_instruments),
            ),
            patch(
                "backend.chain.bybit_client.get_option_tickers",
                new=AsyncMock(side_effect=_fake_tickers),
            ),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_meta(self):
        r = self.client.get("/api/meta")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("BTC", body["underlyings"])
        self.assertIn("cash_secured_put", body["strategies"])
        self.assertIn("sort_fields", body)

    def test_chain_endpoint(self):
        r = self.client.get("/api/chain", params={"underlying": "BTC", "max_dte": 7})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreater(body["count"], 0)
        self.assertIn("symbol", body["contracts"][0])

    def test_chain_endpoint_multi_underlying(self):
        r = self.client.get("/api/chain", params={"underlying": "BTC,ETH", "max_dte": 7})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreater(body["count"], 0)
        underlyings_seen = {c["underlying"] for c in body["contracts"]}
        self.assertIn("BTC", underlyings_seen)
        self.assertIn("ETH", underlyings_seen)

    def test_chain_endpoint_rejects_unsupported_underlying(self):
        r = self.client.get("/api/chain", params={"underlying": "DOGE"})
        self.assertEqual(r.status_code, 400)

    def test_suggestions_endpoint_default(self):
        r = self.client.get("/api/suggestions")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreater(body["count"], 0)
        first = body["suggestions"][0]
        for key in ("strategy", "underlying", "legs", "net_credit", "annualized_yield_pct"):
            self.assertIn(key, first)

    def test_suggestions_endpoint_filters_by_strategy(self):
        r = self.client.get("/api/suggestions", params={"strategies": "cash_secured_put"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(all(s["strategy"] == "cash_secured_put" for s in body["suggestions"]))

    def test_credit_spread_expands_to_both_directions(self):
        # The "credit_spread" engine key expands to bull_put_spread + bear_call_spread;
        # the API should return both sub-strategy names.
        r = self.client.get("/api/suggestions", params={"strategies": "credit_spread"})
        self.assertEqual(r.status_code, 200)
        names = {s["strategy"] for s in r.json()["suggestions"]}
        self.assertIn("bull_put_spread", names)
        self.assertIn("bear_call_spread", names)

    def test_suggestions_endpoint_rejects_unknown_strategy(self):
        r = self.client.get("/api/suggestions", params={"strategies": "not_a_real_strategy"})
        self.assertEqual(r.status_code, 400)

    def test_suggestions_rejects_invalid_sort_by(self):
        r = self.client.get("/api/suggestions", params={"sort_by": "not_a_field"})
        self.assertEqual(r.status_code, 400)

    def test_suggestions_sort_by_dte_days_ascending(self):
        r = self.client.get("/api/suggestions", params={"sort_by": "dte_days", "limit": 100})
        self.assertEqual(r.status_code, 200)
        dtes = [s["dte_days"] for s in r.json()["suggestions"]]
        self.assertEqual(dtes, sorted(dtes), "dte_days should be sorted ascending")

    def test_suggestions_sort_by_max_loss_ascending(self):
        r = self.client.get("/api/suggestions", params={
            "sort_by": "max_loss",
            "strategies": "credit_spread",
            "limit": 100,
        })
        self.assertEqual(r.status_code, 200)
        losses = [s["max_loss"] for s in r.json()["suggestions"]]
        self.assertEqual(losses, sorted(losses), "max_loss should be sorted ascending")

    def test_include_illiquid_flag(self):
        # With the synthetic fixture (all contracts are liquid), both responses
        # should have results. Including illiquid can only increase or equal the count.
        r_liquid = self.client.get("/api/suggestions", params={"include_illiquid": "false", "limit": 500})
        r_all = self.client.get("/api/suggestions", params={"include_illiquid": "true", "limit": 500})
        self.assertEqual(r_liquid.status_code, 200)
        self.assertEqual(r_all.status_code, 200)
        self.assertGreaterEqual(
            r_all.json()["total_before_limit"],
            r_liquid.json()["total_before_limit"],
        )
        # Liquid-only results must contain no illiquid candidates.
        self.assertTrue(
            all(not s["illiquid"] for s in r_liquid.json()["suggestions"]),
            "include_illiquid=false must filter out all illiquid candidates",
        )

    def test_dashboard_index_served(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Short-DTE Income Dashboard", r.text)


if __name__ == "__main__":
    unittest.main()
