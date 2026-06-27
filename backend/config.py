"""
Central configuration / defaults for the short-DTE income dashboard.

Tune these without touching strategy logic.
"""

# Bybit V5 public REST base URL. Swap to api-testnet.bybit.com if you want
# to sanity check connectivity against testnet (testnet options liquidity
# is usually too thin to be useful for real strategy ideas though).
BYBIT_BASE_URL = "https://api.bybit.com"

# Underlyings covered (per project scope: BTC & ETH only for v1).
SUPPORTED_UNDERLYINGS = ["BTC", "ETH"]

# "Short DTE" window. Bybit lists daily expiries on BTC/ETH so 0-7 is the
# practical income-selling window; 0 DTE = expires today.
DEFAULT_MAX_DTE = 7
DEFAULT_MIN_DTE = 0

# Rough delta-magnitude band traders use for premium-selling short strikes.
# 0.10-0.35 covers "far OTM, low risk" through "30-delta, richer premium".
DEFAULT_MIN_ABS_DELTA = 0.10
DEFAULT_MAX_ABS_DELTA = 0.35

# Spread width for vertical credit spreads / iron condor wings, expressed
# as a number of listed strikes away from the short leg (not a fixed $
# amount, since strike spacing differs by underlying/expiry).
DEFAULT_SPREAD_WIDTH_STRIKES = 2

# Liquidity guardrails. Candidates failing these are kept but flagged
# `illiquid=True` rather than silently dropped, so the trader can decide.
MIN_OPEN_INTEREST = 5
MAX_QUOTED_SPREAD_PCT = 0.40  # (ask-bid)/mid

# Assumed risk-free rate for the Black-Scholes probability-of-profit calc.
# Crypto options are typically priced with r ~ 0; left as a knob.
RISK_FREE_RATE = 0.0

HTTP_TIMEOUT_SECONDS = 10.0
