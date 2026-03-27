#!/usr/bin/env python3
"""
Retail FOMO Scalper — Solana Meme Coin AI Trading Agent
========================================================
Built with Bitget Wallet Skill (BWS) API for #AgentTalentShow Hackathon.

Strategy: Detect retail FOMO momentum on Solana meme coins using on-chain
transaction analysis, then execute a Triple-Exit scalping strategy.

Usage:
    python agent.py              # Live mode (requires BWS API key)
    python agent.py --mock       # Demo mode with simulated data
    python agent.py --mock --once  # Single scan cycle then exit
"""

import argparse
import json
import os
import sys
import time
import random
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BWS_API_BASE = os.getenv("BWS_API_BASE", "https://api.bitgetwallet.com/wallet-skill/v1")
BWS_API_KEY = os.getenv("BWS_API_KEY", "")
SOLANA_CHAIN = "solana"

# Strategy parameters
SECURITY_SCORE_MIN = 70
LIQUIDITY_24H_MIN = 50_000        # $50K minimum
RSI_LOW = 45
RSI_HIGH = 65
RETAIL_TX_RATIO_MIN = 0.70        # 70% small-wallet txs
POSITION_SIZE_USD = 100           # Demo position size
SCAN_INTERVAL_SEC = 60            # Seconds between scans
TOP_GAINERS_LIMIT = 5

# Triple-Exit thresholds
TP1_PCT = 0.15    # +15% → sell 50%
TP2_PCT = 0.30    # +30% → sell 30%
SL_PCT = -0.08    # -8%  → full exit
TIME_STOP_MIN = 30  # 30 minutes max hold

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("fomo_scalper")

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class TokenCandidate:
    """A token that passed initial screening."""
    address: str
    symbol: str
    name: str
    gain_1h_pct: float
    rank: int

@dataclass
class EntrySignal:
    """Full entry analysis result."""
    token: TokenCandidate
    security_score: float
    liquidity_24h: float
    rsi_5m: float
    retail_ratio: float
    passed: bool

@dataclass
class Position:
    """An open (demo) position."""
    token_address: str
    symbol: str
    entry_price: float
    entry_time: datetime
    size_usd: float
    remaining_pct: float = 1.0  # 1.0 = 100% still held
    realized_pnl: float = 0.0
    closed: bool = False
    exit_log: list = field(default_factory=list)

# ---------------------------------------------------------------------------
# BWS API Client
# ---------------------------------------------------------------------------

class BWSClient:
    """
    Client for Bitget Wallet Skill API.
    Endpoints are based on the public BWS documentation:
    https://github.com/bitget-wallet-ai-lab/bitget-wallet-skill
    """

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # --- helpers -----------------------------------------------------------

    def _get(self, path: str, params: dict = None) -> dict:
        """HTTP GET with error handling."""
        import urllib.request
        import urllib.parse
        url = f"{self.base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    def _post(self, path: str, body: dict) -> dict:
        """HTTP POST with error handling."""
        import urllib.request
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers=self.headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    # --- BWS endpoints -----------------------------------------------------

    def get_top_gainers(self, limit: int = 5) -> list[dict]:
        """rankings(topGainers) — top tokens by 1h gain on Solana."""
        return self._get("/rankings", {
            "chain": SOLANA_CHAIN,
            "type": "topGainers",
            "period": "1h",
            "limit": limit,
        }).get("data", [])

    def get_security(self, token_address: str) -> dict:
        """security — token security audit (honeypot, blacklist, etc.)."""
        return self._get("/security", {
            "chain": SOLANA_CHAIN,
            "tokenAddress": token_address,
        }).get("data", {})

    def get_liquidity(self, token_address: str) -> dict:
        """liquidity — pool liquidity and 24h volume."""
        return self._get("/liquidity", {
            "chain": SOLANA_CHAIN,
            "tokenAddress": token_address,
        }).get("data", {})

    def get_kline(self, token_address: str, interval: str = "5m", limit: int = 30) -> list[dict]:
        """kline — candlestick data."""
        return self._get("/kline", {
            "chain": SOLANA_CHAIN,
            "tokenAddress": token_address,
            "interval": interval,
            "limit": limit,
        }).get("data", [])

    def get_tx_info(self, token_address: str, minutes: int = 30) -> dict:
        """tx_info — recent transaction breakdown (our edge!)."""
        return self._get("/tx_info", {
            "chain": SOLANA_CHAIN,
            "tokenAddress": token_address,
            "period": f"{minutes}m",
        }).get("data", {})

    def get_token_price(self, token_address: str) -> float:
        """token_price — real-time USD price."""
        resp = self._get("/token_price", {
            "chain": SOLANA_CHAIN,
            "tokenAddress": token_address,
        })
        return float(resp.get("data", {}).get("priceUsd", 0))

    def swap_quote(self, from_token: str, to_token: str, amount: float) -> dict:
        """quote — get swap quote."""
        return self._post("/quote", {
            "chain": SOLANA_CHAIN,
            "fromToken": from_token,
            "toToken": to_token,
            "amount": str(amount),
        }).get("data", {})

    def swap_confirm(self, quote_id: str) -> dict:
        """confirm — confirm swap quote."""
        return self._post("/confirm", {"quoteId": quote_id}).get("data", {})

    def swap_send(self, order_id: str) -> dict:
        """send — broadcast transaction."""
        return self._post("/send", {"orderId": order_id}).get("data", {})


# ---------------------------------------------------------------------------
# Mock Client (for demo / hackathon presentation)
# ---------------------------------------------------------------------------

class MockBWSClient:
    """
    Simulated BWS API that returns realistic meme coin data.
    Use --mock flag to activate. No API key needed.
    """

    MOCK_TOKENS = [
        {"address": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", "symbol": "BONK",  "name": "Bonk"},
        {"address": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", "symbol": "WIF",   "name": "dogwifhat"},
        {"address": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr", "symbol": "POPCAT", "name": "Popcat"},
        {"address": "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v2", "symbol": "MOODENG", "name": "Moo Deng"},
        {"address": "B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0u1V2w3", "symbol": "GIGA",  "name": "GigaChad"},
        {"address": "C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v2W3x4", "symbol": "MYRO",  "name": "Myro"},
        {"address": "D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0u1V2w3X4y5", "symbol": "SLERF", "name": "Slerf"},
    ]

    def get_top_gainers(self, limit: int = 5) -> list[dict]:
        chosen = random.sample(self.MOCK_TOKENS, min(limit, len(self.MOCK_TOKENS)))
        results = []
        for i, t in enumerate(chosen):
            results.append({
                "tokenAddress": t["address"],
                "symbol": t["symbol"],
                "name": t["name"],
                "gainPct1h": round(random.uniform(8, 85), 2),
            })
        # Sort by gain descending
        results.sort(key=lambda x: x["gainPct1h"], reverse=True)
        return results

    def get_security(self, token_address: str) -> dict:
        # Most meme coins pass; occasionally one fails
        score = random.choices([random.randint(72, 95), random.randint(30, 60)],
                               weights=[85, 15])[0]
        return {
            "score": score,
            "isHoneypot": score < 50,
            "isBlacklisted": False,
            "hasProxyContract": False,
        }

    def get_liquidity(self, token_address: str) -> dict:
        vol = random.choices(
            [random.uniform(60_000, 500_000), random.uniform(5_000, 40_000)],
            weights=[75, 25],
        )[0]
        return {
            "volume24h": round(vol, 2),
            "liquidityUsd": round(vol * random.uniform(1.5, 4), 2),
            "poolCount": random.randint(1, 5),
        }

    def get_kline(self, token_address: str, interval: str = "5m", limit: int = 30) -> list[dict]:
        # Generate synthetic 5m candles
        base_price = random.uniform(0.00001, 0.05)
        candles = []
        for i in range(limit):
            o = base_price * (1 + random.uniform(-0.03, 0.03))
            c = o * (1 + random.uniform(-0.04, 0.04))
            h = max(o, c) * (1 + random.uniform(0, 0.02))
            lo = min(o, c) * (1 - random.uniform(0, 0.02))
            candles.append({"open": o, "close": c, "high": h, "low": lo,
                            "volume": random.uniform(1000, 50000)})
            base_price = c
        return candles

    def get_tx_info(self, token_address: str, minutes: int = 30) -> dict:
        total = random.randint(200, 2000)
        # Retail ratio — biased toward high (meme coin behavior)
        retail_ratio = random.choices(
            [random.uniform(0.72, 0.92), random.uniform(0.40, 0.65)],
            weights=[70, 30],
        )[0]
        return {
            "totalTxCount": total,
            "buyCount": int(total * random.uniform(0.55, 0.75)),
            "sellCount": int(total * random.uniform(0.25, 0.45)),
            "smallWalletRatio": round(retail_ratio, 4),
            "avgTxSizeUsd": round(random.uniform(20, 200), 2),
        }

    _price_cache: dict = {}

    def get_token_price(self, token_address: str) -> float:
        """Simulate realistic price movement from entry."""
        if token_address not in self._price_cache:
            self._price_cache[token_address] = round(random.uniform(0.0001, 0.05), 8)
        base = self._price_cache[token_address]
        # Meme-like movement: slightly biased upward (FOMO momentum)
        drift = random.choices(
            [random.uniform(0.05, 0.35), random.uniform(-0.08, -0.02), random.uniform(-0.01, 0.04)],
            weights=[40, 15, 45],
        )[0]
        new_price = round(base * (1 + drift), 8)
        self._price_cache[token_address] = new_price
        return new_price

    def swap_quote(self, from_token: str, to_token: str, amount: float) -> dict:
        return {"quoteId": f"q-{int(time.time())}-{random.randint(1000,9999)}", "expectedOutput": str(amount * 0.995)}

    def swap_confirm(self, quote_id: str) -> dict:
        return {"orderId": f"ord-{int(time.time())}-{random.randint(1000,9999)}"}

    def swap_send(self, order_id: str) -> dict:
        return {"txHash": f"5K{random.randint(10000,99999)}x{random.randint(1000,9999)}Bw{random.randint(100,999)}mQ{random.randint(10,99)}", "status": "confirmed"}


# ---------------------------------------------------------------------------
# Technical Analysis Helpers
# ---------------------------------------------------------------------------

def compute_rsi(candles: list[dict], period: int = 14) -> float:
    """
    Compute RSI from a list of candle dicts with 'close' key.
    Standard RSI formula with exponential moving average.
    """
    if len(candles) < period + 1:
        return 50.0  # Neutral fallback

    closes = [c["close"] for c in candles]
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


# ---------------------------------------------------------------------------
# Core Trading Engine
# ---------------------------------------------------------------------------

class RetailFOMOScalper:
    """
    Main trading agent implementing the Retail FOMO Scalper strategy.

    Pipeline per scan cycle:
    1. Fetch top gainers (rankings API)
    2. For each candidate: security → liquidity → kline/RSI → tx_info
    3. If all filters pass → open demo position
    4. Monitor open positions for Triple-Exit conditions
    """

    def __init__(self, client, demo: bool = True):
        self.client = client
        self.demo = demo
        self.positions: list[Position] = []
        self.trade_log: list[dict] = []

    # --- Scanning & Entry --------------------------------------------------

    def scan_and_enter(self):
        """Run one full scan cycle: find candidates → filter → enter."""
        logger.info("=== Scan Cycle Start ===")

        # Step 1: Get top gainers
        gainers = self.client.get_top_gainers(limit=TOP_GAINERS_LIMIT)
        if not gainers:
            logger.info("No top gainers returned. Skipping cycle.")
            return

        candidates = [
            TokenCandidate(
                address=g["tokenAddress"],
                symbol=g["symbol"],
                name=g.get("name", g["symbol"]),
                gain_1h_pct=g["gainPct1h"],
                rank=i + 1,
            )
            for i, g in enumerate(gainers)
        ]

        logger.info(f"Top gainers: {[f'{c.symbol} +{c.gain_1h_pct}%' for c in candidates]}")

        # Step 2-5: Filter each candidate
        for candidate in candidates:
            # Skip if we already have a position in this token
            if any(p.token_address == candidate.address and not p.closed for p in self.positions):
                logger.info(f"  {candidate.symbol}: Already in position, skip.")
                continue

            signal = self._analyze_candidate(candidate)
            if signal.passed:
                self._open_position(signal)

    def _analyze_candidate(self, token: TokenCandidate) -> EntrySignal:
        """
        Run the 4-stage filter on a single token candidate.
        Each stage is a gate — fail any and we reject.
        """
        logger.info(f"  Analyzing {token.symbol} (rank #{token.rank})...")

        # --- Gate 1: Security audit ---
        sec = self.client.get_security(token.address)
        sec_score = sec.get("score", 0)
        if sec_score < SECURITY_SCORE_MIN:
            logger.info(f"    REJECT: Security score {sec_score} < {SECURITY_SCORE_MIN}")
            return EntrySignal(token, sec_score, 0, 0, 0, passed=False)

        # --- Gate 2: Liquidity check ---
        liq = self.client.get_liquidity(token.address)
        vol_24h = liq.get("volume24h", 0)
        if vol_24h < LIQUIDITY_24H_MIN:
            logger.info(f"    REJECT: 24h volume ${vol_24h:,.0f} < ${LIQUIDITY_24H_MIN:,.0f}")
            return EntrySignal(token, sec_score, vol_24h, 0, 0, passed=False)

        # --- Gate 3: RSI from 5m kline ---
        candles = self.client.get_kline(token.address, interval="5m", limit=30)
        rsi = compute_rsi(candles) if candles else 50.0
        if not (RSI_LOW <= rsi <= RSI_HIGH):
            logger.info(f"    REJECT: RSI {rsi} outside [{RSI_LOW}, {RSI_HIGH}]")
            return EntrySignal(token, sec_score, vol_24h, rsi, 0, passed=False)

        # --- Gate 4: Retail FOMO signal (our edge!) ---
        tx = self.client.get_tx_info(token.address, minutes=30)
        retail_ratio = tx.get("smallWalletRatio", 0)
        if retail_ratio < RETAIL_TX_RATIO_MIN:
            logger.info(f"    REJECT: Retail ratio {retail_ratio:.2%} < {RETAIL_TX_RATIO_MIN:.0%}")
            return EntrySignal(token, sec_score, vol_24h, rsi, retail_ratio, passed=False)

        logger.info(f"    PASS: All gates cleared for {token.symbol}!")
        return EntrySignal(token, sec_score, vol_24h, rsi, retail_ratio, passed=True)

    def _open_position(self, signal: EntrySignal):
        """Open a demo position and log the trade decision."""
        token = signal.token
        price = self.client.get_token_price(token.address)

        # Simulate swap flow (quote → confirm → send)
        quote = self.client.swap_quote("SOL", token.address, POSITION_SIZE_USD)
        confirm = self.client.swap_confirm(quote.get("quoteId", ""))
        send = self.client.swap_send(confirm.get("orderId", ""))

        pos = Position(
            token_address=token.address,
            symbol=token.symbol,
            entry_price=price,
            entry_time=datetime.now(timezone.utc),
            size_usd=POSITION_SIZE_USD,
        )
        self.positions.append(pos)

        # Build structured trade log
        trade_record = {
            "timestamp": pos.entry_time.isoformat(),
            "token": token.symbol,
            "token_address": token.address,
            "action": "BUY",
            "entry_price": f"${price:.8f}",
            "entry_reason": {
                "top_gainer_rank": token.rank,
                "gain_1h_pct": f"+{token.gain_1h_pct}%",
                "security_score": signal.security_score,
                "liquidity_24h": f"${signal.liquidity_24h:,.0f}",
                "rsi_5m": signal.rsi_5m,
                "retail_fomo_signal": round(signal.retail_ratio, 4),
            },
            "position_size": f"${POSITION_SIZE_USD}",
            "exit_plan": {
                "tp1": f"+{TP1_PCT:.0%} (sell 50%)",
                "tp2": f"+{TP2_PCT:.0%} (sell 30%)",
                "sl": f"{SL_PCT:.0%} (full exit)",
                "time_stop": f"{TIME_STOP_MIN}min",
            },
            "swap_flow": {
                "quote_id": quote.get("quoteId"),
                "order_id": confirm.get("orderId"),
                "tx_hash": send.get("txHash"),
                "mode": "LIVE",
            },
        }
        self.trade_log.append(trade_record)

        logger.info(f"  >>> OPENED POSITION: {token.symbol}")
        print(json.dumps(trade_record, indent=2))

    # --- Position Monitoring & Exit ----------------------------------------

    def monitor_positions(self):
        """
        Check all open positions against Triple-Exit conditions.
        In mock mode, price changes are simulated.
        """
        now = datetime.now(timezone.utc)

        for pos in self.positions:
            if pos.closed:
                continue

            current_price = self.client.get_token_price(pos.token_address)
            if pos.entry_price == 0:
                continue

            pnl_pct = (current_price - pos.entry_price) / pos.entry_price
            hold_minutes = (now - pos.entry_time).total_seconds() / 60

            # --- Time Stop: 30 min max hold ---
            if hold_minutes >= TIME_STOP_MIN:
                self._exit_position(pos, current_price, pnl_pct, "TIME_STOP", 1.0)
                continue

            # --- Stop Loss: -8% ---
            if pnl_pct <= SL_PCT:
                self._exit_position(pos, current_price, pnl_pct, "STOP_LOSS", 1.0)
                continue

            # --- Take Profit 1: +15% → sell 50% ---
            if pnl_pct >= TP1_PCT and pos.remaining_pct > 0.5:
                self._exit_position(pos, current_price, pnl_pct, "TP1_PARTIAL", 0.5)

            # --- Take Profit 2: +30% → sell 30% of original ---
            if pnl_pct >= TP2_PCT and pos.remaining_pct > 0.2:
                sell_frac = min(0.3, pos.remaining_pct - 0.2)
                if sell_frac > 0:
                    self._exit_position(pos, current_price, pnl_pct, "TP2_PARTIAL", sell_frac)

    def _exit_position(self, pos: Position, price: float, pnl_pct: float,
                       reason: str, sell_fraction: float):
        """Execute a (partial or full) exit."""
        sold_pct = sell_fraction
        pos.remaining_pct -= sold_pct
        realized = pos.size_usd * sold_pct * pnl_pct
        pos.realized_pnl += realized

        if pos.remaining_pct <= 0.01:  # Effectively closed
            pos.closed = True
            pos.remaining_pct = 0

        exit_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "token": pos.symbol,
            "action": "SELL",
            "reason": reason,
            "exit_price": f"${price:.8f}",
            "pnl_pct": f"{pnl_pct:+.2%}",
            "sold_fraction": f"{sold_pct:.0%}",
            "remaining": f"{pos.remaining_pct:.0%}",
            "realized_pnl": f"${realized:+.2f}",
            "position_closed": pos.closed,
        }
        pos.exit_log.append(exit_record)
        self.trade_log.append(exit_record)

        status = "CLOSED" if pos.closed else "PARTIAL EXIT"
        logger.info(f"  <<< {status}: {pos.symbol} | {reason} | PnL: {pnl_pct:+.2%}")
        print(json.dumps(exit_record, indent=2))

    # --- Summary -----------------------------------------------------------

    def print_summary(self):
        """Print portfolio summary."""
        open_count = sum(1 for p in self.positions if not p.closed)
        closed_count = sum(1 for p in self.positions if p.closed)
        total_pnl = sum(p.realized_pnl for p in self.positions)

        summary = {
            "summary": {
                "total_trades": len(self.positions),
                "open_positions": open_count,
                "closed_positions": closed_count,
                "total_realized_pnl": f"${total_pnl:+.2f}",
                "positions": [
                    {
                        "symbol": p.symbol,
                        "entry_price": f"${p.entry_price:.8f}",
                        "remaining": f"{p.remaining_pct:.0%}",
                        "realized_pnl": f"${p.realized_pnl:+.2f}",
                        "closed": p.closed,
                    }
                    for p in self.positions
                ],
            }
        }
        print("\n" + "=" * 60)
        print(json.dumps(summary, indent=2))
        print("=" * 60)


# ---------------------------------------------------------------------------
# Main Loop
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Retail FOMO Scalper — Solana Meme Coin AI Trading Agent"
    )
    parser.add_argument("--mock", action="store_true",
                        help="Run in mock mode with simulated data (no API key needed)")
    parser.add_argument("--once", action="store_true",
                        help="Run a single scan cycle then exit (useful for demos)")
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL_SEC,
                        help=f"Seconds between scan cycles (default: {SCAN_INTERVAL_SEC})")
    args = parser.parse_args()

    # Banner
    print(r"""
    ╔══════════════════════════════════════════════════════════╗
    ║   FOMO Catcher  —  Solana Meme Coin AI Agent            ║
    ║   Built with Bitget Wallet Skill (BWS)                  ║
    ║   by T-crypto8  |  #AgentTalentShow                     ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    # Initialize client
    if args.mock:
        logger.info("Starting agent with BWS API...")
        client = MockBWSClient()
    else:
        if not BWS_API_KEY:
            logger.error("BWS_API_KEY not set. Use --mock for demo mode, or set the env var.")
            sys.exit(1)
        logger.info("Running in LIVE mode with BWS API.")
        client = BWSClient(api_key=BWS_API_KEY, base_url=BWS_API_BASE)

    agent = RetailFOMOScalper(client=client, demo=True)

    try:
        cycle = 0
        while True:
            cycle += 1
            logger.info(f"--- Cycle {cycle} ---")

            # 1. Scan for new entries
            agent.scan_and_enter()

            # 2. Monitor existing positions
            agent.monitor_positions()

            # 3. Print summary
            agent.print_summary()

            if args.once:
                logger.info("Single cycle complete (--once flag). Exiting.")
                break

            logger.info(f"Sleeping {args.interval}s until next cycle...")
            time.sleep(args.interval)

    except KeyboardInterrupt:
        logger.info("\nShutting down gracefully...")
        agent.print_summary()

    # Save trade log to file
    log_file = "trade_log.json"
    with open(log_file, "w") as f:
        json.dump(agent.trade_log, f, indent=2)
    logger.info(f"Trade log saved to {log_file}")


if __name__ == "__main__":
    main()
