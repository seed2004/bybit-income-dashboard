# Bybit Short-DTE Income Dashboard

A local web service that pulls Bybit's live BTC/ETH options chain and screens
it for short-DTE, premium-selling cashflow trades: cash-secured short puts,
covered calls, vertical credit spreads (bull put / bear call), iron condors,
and short strangles.

This is **Phase 1**: read-only, public market data, suggestions only. It
does not hold API keys and cannot place orders yet. See "Roadmap" below.

## What it does

1. Pulls the live option chain for BTC and/or ETH from Bybit's public V5
   market-data endpoints (`/v5/market/instruments-info`,
   `/v5/market/tickers`) — no account, no API key required.
2. Filters to a short-DTE window (default 0-7 days; Bybit lists daily
   expiries on BTC/ETH so this is a real, tradable window).
3. Scans every strike for each of the four strategy families and ranks
   them by annualized yield, with a model-based probability-of-profit
   estimate for each candidate.
4. Serves a dashboard (`/`) where you filter by underlying, strategy,
   DTE, delta band, and spread width, and review ranked ideas before
   placing the trade yourself on Bybit.

## Strategies implemented

| Strategy | Risk | What it is |
|---|---|---|
| `cash_secured_put` | Capped at strike | Sell an OTM put, collateral = strike. |
| `covered_call` | Undefined (you hold the underlying) | Sell an OTM call against held spot/perp. |
| `bull_put_spread` / `bear_call_spread` (`credit_spread`) | Defined (width − credit) | Sell a strike, buy a further-OTM strike for protection. |
| `iron_condor` / `short_strangle` (`iron_condor`) | Defined / undefined respectively | Sell a put + a call on the same expiry, with or without protective wings. |

Every candidate reports: legs, net credit, max loss (or `undefined_risk`
flag), breakeven(s), a Black-Scholes probability-of-profit estimate, and
annualized yield on capital at risk. The math lives in
`backend/strategies/common.py` and the per-strategy files — read those
docstrings before trusting a number, especially the POP estimate (it
assumes IV is an unbiased forecast and returns are lognormal, which is a
simplification for crypto).

## Setup

```bash
cd bybit-income-dashboard
python3 -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
```

## Run

```bash
uvicorn backend.app:app --reload --port 8000
```

Open **http://localhost:8000/** and click "Scan chain".

## Before you trust this with real money

This was built in a sandboxed dev environment with no network access to
`api.bybit.com` (corporate proxy allowlist blocked it, confirmed via
direct test). Every line of API-calling code was written against Bybit's
documented V5 schema, and the strategy math was verified offline against
a synthetic-but-internally-consistent fixture chain (`tests/`, 16 passing
tests) — but **none of it has touched a live Bybit response yet**.

Before relying on this for real trades, on a machine with normal internet
access:

1. `pip install -r requirements.txt`, run the server, and load the
   dashboard. Confirm `/api/chain?underlying=BTC` returns real strikes
   that match what you see in the Bybit options UI.
2. Spot-check 2-3 suggested trades by hand: does the premium match the
   live bid/ask on Bybit, does the breakeven math check out, is the DTE
   correct?
3. Only then start using the suggestions to inform real position sizing.

## Project layout

```
backend/
  config.py              defaults (DTE window, delta band, spread width...)
  bybit_client.py         public REST calls (instruments-info, tickers)
  chain.py                merges instruments+tickers -> OptionContract, DTE filter
  models.py                OptionContract / StrategyCandidate / StrategyLeg
  strategies/
    common.py              Black-Scholes POP, annualized yield, strike/wing selection
    cash_secured_put.py
    covered_call.py
    credit_spread.py        bull put + bear call spreads
    iron_condor.py           iron condor + short strangle
    engine.py                orchestrator: groups by expiry, runs requested strategies
  app.py                    FastAPI routes + static dashboard mount
frontend/
  index.html                single-file dashboard (vanilla JS, no build step)
tests/
  test_strategies.py        offline unit tests (no network needed)
  fixtures/sample_data.py   synthetic chain generator for tests
```

## API reference (for scripting against it yourself)

- `GET /api/health` — liveness + supported underlyings.
- `GET /api/meta` — strategy names, underlyings, and current defaults (drives the dashboard's filter UI).
- `GET /api/chain?underlying=BTC,ETH&min_dte=0&max_dte=7` — raw merged chain.
- `GET /api/suggestions?underlying=BTC,ETH&strategies=cash_secured_put,credit_spread&min_dte=0&max_dte=7&min_abs_delta=0.1&max_abs_delta=0.35&width_strikes=2&sort_by=annualized_yield_pct&limit=50&include_illiquid=false` — ranked trade ideas.

## Roadmap (explicitly out of scope for this build)

**Phase 2 — account connection + confirm-to-execute order placement.**
You chose "suggest + one-click confirm" as the target execution model.
To build it:
- Add `backend/bybit_private_client.py`: HMAC-signed requests using your
  API key/secret (read from environment variables or a local `.env` —
  never hardcoded, never logged).
- Add `GET /api/account` (wallet balance, open option positions, current
  Greeks exposure) so the dashboard shows what you actually hold.
- Add `POST /api/orders/preview` (returns the exact `category=option`
  order payload for a chosen candidate) and `POST /api/orders/confirm`
  (places it via `/v5/order/create` only after this explicit second call
  — never auto-fire off the suggestion endpoint).
- Start against Bybit **testnet** keys and place a handful of real test
  orders before pointing it at mainnet keys.

**Phase 3 — live data + automation quality-of-life.**
- WebSocket subscription (`/v5/ws/connect`, public option topics) so the
  dashboard updates without manual refresh / polling.
- A scheduled daily run ("today's best short-DTE income ideas") — once
  this app is running somewhere persistent, this is a natural fit for a
  recurring job that pings you with the top candidates each morning.
- Paper-trading log: record suggestions you acted on and what they
  actually closed at, to validate the POP/yield model against reality
  over time.

Tell me when you're ready for Phase 2 and I'll pick it up as its own
focused task — it needs your API keys and careful handling, so it's kept
separate on purpose.
