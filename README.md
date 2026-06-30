# Bybit Short-DTE Income Dashboard

A local web app for BTC and ETH options traders on Bybit. It pulls live market data, screens the option chain for premium-selling opportunities, tracks your open positions, and flags potential arbitrage mispricings — all from a single browser tab. No API key required to get started.

---

## What you can do with it

| Tab | What it does |
|---|---|
| **Suggestions** | Scan the live chain and rank short-DTE income trades by yield |
| **Strike Ladder** | Compare every strike for a chosen expiry side-by-side |
| **Portfolio** | Log your open legs and cycles, track P&L and Greeks |
| **Intelligence** | Read market sentiment from PCR, GEX, IV skew, and term structure |
| **Arb Scanner** | Detect mispricings between options and the perpetual contract |
| **Settings** | (Optional) Enter Bybit API key to import live positions |

---

## Quick start

**Requirements:** Python 3.10+

```bash
cd bybit-income-dashboard

# 1. Create a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start the server
uvicorn backend.app:app --reload --port 8000
```

Open **http://localhost:8000** in your browser. That's it — no API key needed for market data.

---

## Tabs explained

### Suggestions

The core screener. Pick your filters and click **Scan chain**.

| Filter | What it controls |
|---|---|
| Underlying | BTC, ETH, or both |
| Strategy | Which strategy family to scan (see table below) |
| DTE range | Days to expiry — default 0–7 days |
| Delta band | How far OTM to look — default 0.10–0.35 |
| Spread width | For credit spreads / iron condors: how many strikes wide |

Results are ranked by **annualised yield on capital at risk**. Each row shows:
- Legs (strikes, type, expiry)
- Net credit received
- Breakeven price(s)
- Max loss
- Probability of Profit (Black-Scholes estimate)
- Annualised yield %
- Liquidity flag (illiquid = wide spread or low OI)

**Strategies screened:**

| Strategy | Risk profile | Description |
|---|---|---|
| Cash-secured put | Limited (strike − credit) | Sell an OTM put. Collateral = strike × contract size |
| Covered call | Upside capped | Sell an OTM call against your spot/perp holding |
| Bull put spread | Defined (width − credit) | Sell a put, buy a lower-strike put for protection |
| Bear call spread | Defined (width − credit) | Sell a call, buy a higher-strike call for protection |
| Iron condor | Defined | Bull put spread + bear call spread on the same expiry |
| Short strangle | Undefined | Sell an OTM put + an OTM call, no protective wings |

---

### Strike Ladder

Compares every available strike for a single expiry and option type (calls or puts) in one table. Useful for answering "which strike is most interesting to sell today?"

**How to use:**
1. Pick underlying (BTC / ETH)
2. Pick expiry from the dropdown
3. Pick option type (Puts / Calls)
4. Optionally set an OTM % range to filter the strikes shown
5. Click **Run ladder**

Each row shows for that strike:
- Bid / Ask / Mark price and IV
- Delta, Theta
- Annualised yield and breakeven
- OTM % distance from spot
- Blended Probability of Profit
- IV vs Realized Volatility ratio (IV/RV > 1 = vol premium, good for sellers)
- IV rank vs recent history
- Composite score — a single 0–100 number combining yield, POP, and vol premium

Rows are sorted by composite score. The best strike to sell will be at the top.

---

### Portfolio

Track your open trades without needing a Bybit account connection.

**Two ways to add a leg:**

1. **Manual entry** — fill in strike, type, expiry, credit, and quantity and click **Add SELL leg**
2. **Import from Bybit** — go to Settings, enter an API key (read-only), then click **Import from Bybit** on the Portfolio tab

**Cycles** let you group related legs together (e.g., both legs of a spread, or a roll from one strike to another). You can:
- Create a cycle and name it
- Assign / unassign legs to a cycle
- Mark a cycle complete when all legs are closed

**Closing a leg:** click Close on any open leg, enter the closing price, and the leg moves to the Closed Legs table with realised P&L calculated.

**What the portfolio shows:**
- Open legs: entry credit, current mark, unrealised P&L, Greeks
- Closed legs: entry credit, closing debit, net P&L, hold duration
- Cycles summary: total credit, total P&L, status

---

### Intelligence

A market analysis dashboard that reads the full option chain and surfaces sentiment signals. Click **Scan** to load.

| Signal | What it means |
|---|---|
| **Put/Call Ratio (PCR)** | > 1 = more put volume than calls = bearish sentiment (or protective buying) |
| **Max Pain** | The price where option sellers collectively lose the least — a gravitational level near expiry |
| **Gamma Exposure (GEX)** | Positive = dealers are long gamma (stabilising), Negative = dealers are short gamma (amplifying moves) |
| **IV Skew** | How much more expensive puts are vs calls at the same delta — elevated skew = fear premium |
| **Term Structure** | Near-term IV vs far-term IV — backwardation (near > far) often signals stress |
| **Signal digest** | Plain-English summary combining all five signals into an overall market read |

Four charts are shown:
- OI by strike (mirrored calls vs puts bar chart) — shows where open interest is clustered
- GEX by strike — shows dealer hedging pressure at each price level
- IV skew curve — shows the vol premium across OTM puts and calls
- Term structure — shows IV across expiries

---

### Arb Scanner

Scans for theoretical mispricings between Bybit options and the perpetual contract. These are educational signals — always account for execution cost, slippage, and funding before acting.

Click **Scan arb →** to load. The scanner runs three screens:

**1. Synthetic forward vs perpetual**

A synthetic forward is built from options: `Call_mid − Put_mid + Strike`. If this differs significantly from the perp mark price, there may be a basis trade.

- Positive basis → short perp, long synthetic (buy call + sell put)
- Negative basis → long perp, short synthetic (sell call + buy put)
- Net edge = |basis| − execution cost − funding carry to expiry

**2. Put-call parity gaps**

Parity requires `Call − Put = Spot − Strike`. A gap wider than the combined bid-ask spread indicates a mispricing.

- Gap positive → sell call, buy put, buy spot
- Gap negative → buy call, sell put, sell spot

**3. Box spread**

A box spread (bull call spread + bear put spread at the same strikes) always pays `K₂ − K₁` at expiry. If you can buy the box for less than `K₂ − K₁`, the difference is theoretically risk-free profit.

The **perp context bar** at the top shows the current funding rate, annualised carry estimate, and basis — useful for sizing the cost of holding a perp hedge.

The **Development Roadmap** section (collapsible, bottom of tab) lists planned features for future phases.

---

### Settings

Enter a Bybit read-only API key to enable live position import. The key is stored locally in `data/credentials.json` — it never leaves your machine.

Fields:
- **API Key** — from Bybit > Account > API Management
- **API Secret** — paired secret for the key above

The key only needs **read** permissions (positions, orders). It cannot be used to place trades from this app in the current version.

---

## Data and privacy

- All market data comes from Bybit's **public** V5 REST API — no account needed
- Portfolio data is stored in **local JSON files** (`data/`) — nothing is sent anywhere
- API credentials (if entered) are stored **locally only** and used only to read your positions from Bybit
- The app has no telemetry, no analytics, and no external dependencies beyond Bybit's API

---

## Project layout

```
bybit-income-dashboard/
├── backend/
│   ├── app.py                 FastAPI routes and business logic
│   ├── bybit_client.py        Bybit V5 public REST calls (read-only)
│   ├── chain.py               Merges instruments + tickers → OptionContract
│   ├── models.py              OptionContract, StrategyCandidate, StrategyLeg
│   ├── atr.py                 Realized volatility, IV rank, POP calibration
│   ├── cycles.py              Trade cycle / group management
│   ├── config.py              Default parameters (DTE, delta, spread width)
│   └── strategies/
│       ├── common.py          Black-Scholes POP, yield math, wing selection
│       ├── cash_secured_put.py
│       ├── covered_call.py
│       ├── credit_spread.py   Bull put + bear call spreads
│       ├── iron_condor.py     Iron condor + short strangle
│       └── engine.py          Orchestrator: groups by expiry, runs strategies
├── frontend/
│   └── index.html             Single-file dashboard (vanilla JS, no build step)
├── tests/
│   └── test_suite.py          118 test cases (run with pytest)
├── data/                      Auto-created; stores portfolio and credentials
└── requirements.txt
```

---

## API reference

If you want to query the backend directly (e.g., from a script):

| Endpoint | Description |
|---|---|
| `GET /api/health` | Liveness check |
| `GET /api/meta` | Strategy names, underlyings, current defaults |
| `GET /api/chain?underlying=BTC` | Raw merged option chain |
| `GET /api/suggestions?underlying=BTC&strategies=cash_secured_put&max_dte=7` | Ranked trade ideas |
| `GET /api/chain/expiries?underlying=BTC` | List of available expiry dates |
| `GET /api/chain/ladder?underlying=BTC&expiry=2026-07-04&option_type=P` | Strike ladder for one expiry |
| `GET /api/market/intelligence?underlying=BTC` | Full market analysis (PCR, GEX, skew, term structure) |
| `GET /api/arb/scan?underlying=BTC` | Arb scanner: synthetic vs perp, parity gaps, box spreads |
| `GET /api/portfolio` | Open legs |
| `GET /api/portfolio/closed` | Closed legs |
| `GET /api/portfolio/cycles` | Cycles with enriched P&L |
| `GET /api/bybit/positions` | Live positions from Bybit (requires API key in Settings) |

---

## Running tests

```bash
pytest tests/test_suite.py -v
```

118 tests covering API routes, strategy math, portfolio CRUD, cycle management, intelligence signals, and arb scan computations. All run offline with no network access needed.

---

## Roadmap

**Phase 2 — Order placement**
- Private API integration (HMAC-signed, read from environment variables)
- One-click order confirmation from Suggestions and Ladder tabs
- Delta hedge tracker: track net delta across your portfolio, suggest hedge trades

**Phase 3 — Historical data**
- Daily IV snapshot storage for true IV rank (instead of the current HV proxy)
- Funding rate history chart (30-day annualised funding vs IV)
- Calendar spread arb baseline (requires stored term structure history)
- Backtest framework: replay historical snapshots through the arb screens

**Phase 4 — Advanced signals**
- Volatility surface fitting (SVI model) — flag contracts deviating from the fitted surface
- Cross-exchange basis (Bybit vs Deribit)
- Event vol premium detection and systematic skew trading
