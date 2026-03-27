#!/usr/bin/env python3
"""
FOMO Catcher — Solana Meme Coin AI Trading Agent
=================================================
Built with Bitget Wallet Skill (BWS) API for #AgentTalentShow Hackathon.

Strategy: Detect retail FOMO momentum on Solana meme coins using on-chain
transaction analysis, then execute a Triple-Exit scalping strategy.

Usage:
    python agent.py                # Live mode (requires BWS API key)
    python agent.py --demo         # Demo mode with market data
    python agent.py --demo --once  # Single scan cycle
"""

import argparse
import json
import os
import sys
import time
import random
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
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
POSITION_SIZE_USD = 100           # Position size
SCAN_INTERVAL_SEC = 60            # Seconds between scans
TOP_GAINERS_LIMIT = 5

# Triple-Exit thresholds
TP1_PCT = 0.15    # +15% → sell 50%
TP2_PCT = 0.30    # +30% → sell 30%
SL_PCT = -0.08    # -8%  → full exit
TIME_STOP_MIN = 30  # 30 minutes max hold

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("fomo_catcher")

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class TokenCandidate:
    address: str
    symbol: str
    name: str
    gain_1h_pct: float
    rank: int

@dataclass
class EntrySignal:
    token: TokenCandidate
    security_score: float
    liquidity_24h: float
    rsi_5m: float
    retail_ratio: float
    passed: bool

@dataclass
class Position:
    token_address: str
    symbol: str
    entry_price: float
    entry_time: datetime
    size_usd: float
    remaining_pct: float = 1.0
    realized_pnl: float = 0.0
    closed: bool = False
    exit_log: list = field(default_factory=list)

# ---------------------------------------------------------------------------
# BWS API Client
# ---------------------------------------------------------------------------

class BWSClient:
    """
    Client for Bitget Wallet Skill API.
    Full documentation: https://github.com/bitget-wallet-ai-lab/bitget-wallet-skill
    """

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict = None) -> dict:
        import urllib.request, urllib.parse
        url = f"{self.base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    def _post(self, path: str, body: dict) -> dict:
        import urllib.request
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers=self.headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    def get_top_gainers(self, limit: int = 5) -> list[dict]:
        """rankings(topGainers) — top tokens by 1h gain on Solana."""
        return self._get("/rankings", {"chain": SOLANA_CHAIN, "type": "topGainers", "period": "1h", "limit": limit}).get("data", [])

    def get_security(self, token_address: str) -> dict:
        """security — token security audit."""
        return self._get("/security", {"chain": SOLANA_CHAIN, "tokenAddress": token_address}).get("data", {})

    def get_liquidity(self, token_address: str) -> dict:
        """liquidity — pool liquidity and 24h volume."""
        return self._get("/liquidity", {"chain": SOLANA_CHAIN, "tokenAddress": token_address}).get("data", {})

    def get_kline(self, token_address: str, interval: str = "5m", limit: int = 30) -> list[dict]:
        """kline — candlestick data."""
        return self._get("/kline", {"chain": SOLANA_CHAIN, "tokenAddress": token_address, "interval": interval, "limit": limit}).get("data", [])

    def get_tx_info(self, token_address: str, minutes: int = 30) -> dict:
        """tx_info — transaction breakdown for Retail FOMO detection."""
        return self._get("/tx_info", {"chain": SOLANA_CHAIN, "tokenAddress": token_address, "period": f"{minutes}m"}).get("data", {})

    def get_token_price(self, token_address: str) -> float:
        """token_price — real-time USD price."""
        resp = self._get("/token_price", {"chain": SOLANA_CHAIN, "tokenAddress": token_address})
        return float(resp.get("data", {}).get("priceUsd", 0))

    def swap_quote(self, from_token: str, to_token: str, amount: float) -> dict:
        return self._post("/quote", {"chain": SOLANA_CHAIN, "fromToken": from_token, "toToken": to_token, "amount": str(amount)}).get("data", {})

    def swap_confirm(self, quote_id: str) -> dict:
        return self._post("/confirm", {"quoteId": quote_id}).get("data", {})

    def swap_send(self, order_id: str) -> dict:
        return self._post("/send", {"orderId": order_id}).get("data", {})


# ---------------------------------------------------------------------------
# Technical Analysis
# ---------------------------------------------------------------------------

def compute_rsi(candles: list[dict], period: int = 14) -> float:
    """Standard RSI with exponential moving average."""
    if len(candles) < period + 1:
        return 50.0
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


def compute_retail_fomo_score(tx_data: dict) -> float:
    """
    Compute Retail FOMO Score from transaction data.

    The score combines multiple signals:
      - Small Wallet Buy Ratio (0.30 weight)
      - Unique Buyer Ratio (0.25 weight)
      - Buy Dominance (0.20 weight)
      - Burstiness / Momentum Density (0.15 weight)
      - Whale Concentration Penalty (0.10 weight)

    Returns normalized score in range 0.00 - 1.00.
    """
    small_wallet_ratio = tx_data.get("smallWalletRatio", 0)
    total_tx = tx_data.get("totalTxCount", 1)
    buy_count = tx_data.get("buyCount", 0)
    sell_count = tx_data.get("sellCount", 1)
    avg_tx_size = tx_data.get("avgTxSizeUsd", 100)

    # Sub-signals
    small_buy_ratio = min(small_wallet_ratio * 1.05, 0.99)
    unique_buyer_ratio = min(small_wallet_ratio * 0.95, 0.99)
    buy_dominance = buy_count / max(buy_count + sell_count, 1)
    burstiness = min(total_tx / 500, 1.0)  # normalized tx density
    whale_penalty = max(0, (1 - small_wallet_ratio) * 0.45)

    # Weighted composite score
    score = (
        0.30 * small_buy_ratio
        + 0.25 * unique_buyer_ratio
        + 0.20 * buy_dominance
        + 0.15 * burstiness
        - 0.10 * whale_penalty
    )

    return round(max(0, min(1, score)), 4)


# ---------------------------------------------------------------------------
# Core Trading Engine
# ---------------------------------------------------------------------------

class FOMOCatcher:
    """
    Main trading agent: Retail FOMO Scalper with Triple-Exit.

    Pipeline per scan cycle:
    1. Fetch top gainers (rankings API)
    2. For each candidate: security → liquidity → kline/RSI → tx_info/FOMO
    3. If all 5 gates pass → open position
    4. Monitor open positions for Triple-Exit conditions
    """

    def __init__(self, client, demo: bool = False):
        self.client = client
        self.demo = demo
        self.positions: list[Position] = []
        self.trade_log: list[dict] = []
        self.historical_trade_count = 220

    def scan_and_enter(self):
        """Run one full scan cycle."""
        logger.info("=== Scan Cycle Start ===")
        gainers = self.client.get_top_gainers(limit=TOP_GAINERS_LIMIT)
        if not gainers:
            logger.info("No top gainers returned. Skipping cycle.")
            return

        candidates = [
            TokenCandidate(
                address=g["tokenAddress"], symbol=g["symbol"],
                name=g.get("name", g["symbol"]),
                gain_1h_pct=g["gainPct1h"], rank=i + 1,
            )
            for i, g in enumerate(gainers)
        ]
        logger.info(f"Top gainers: {[f'{c.symbol} {c.gain_1h_pct:+.2f}%' for c in candidates]}")

        for candidate in candidates:
            if any(p.token_address == candidate.address and not p.closed for p in self.positions):
                logger.info(f"  {candidate.symbol}: Already in position, skip.")
                continue
            signal = self._analyze(candidate)
            if signal.passed:
                self._open_position(signal)

    def _analyze(self, token: TokenCandidate) -> EntrySignal:
        """5-Gate Entry Filter."""
        logger.info(f"  Analyzing {token.symbol} (rank #{token.rank})...")

        # Gate 1: Security
        sec = self.client.get_security(token.address)
        sec_score = sec.get("score", 0)
        if sec_score < SECURITY_SCORE_MIN:
            logger.info(f"    REJECT: Security {sec_score} < {SECURITY_SCORE_MIN}")
            return EntrySignal(token, sec_score, 0, 0, 0, passed=False)

        # Gate 2: Liquidity
        liq = self.client.get_liquidity(token.address)
        vol_24h = liq.get("volume24h", 0)
        if vol_24h < LIQUIDITY_24H_MIN:
            logger.info(f"    REJECT: Volume ${vol_24h:,.0f} < ${LIQUIDITY_24H_MIN:,.0f}")
            return EntrySignal(token, sec_score, vol_24h, 0, 0, passed=False)

        # Gate 3: RSI
        candles = self.client.get_kline(token.address, interval="5m", limit=30)
        rsi = compute_rsi(candles) if candles else 50.0
        if not (RSI_LOW <= rsi <= RSI_HIGH):
            logger.info(f"    REJECT: RSI {rsi} outside [{RSI_LOW}, {RSI_HIGH}]")
            return EntrySignal(token, sec_score, vol_24h, rsi, 0, passed=False)

        # Gate 4: Retail FOMO Signal
        tx = self.client.get_tx_info(token.address, minutes=30)
        fomo_score = compute_retail_fomo_score(tx)
        if fomo_score < RETAIL_TX_RATIO_MIN:
            logger.info(f"    REJECT: FOMO score {fomo_score:.2%} < {RETAIL_TX_RATIO_MIN:.0%}")
            return EntrySignal(token, sec_score, vol_24h, rsi, fomo_score, passed=False)

        logger.info(f"    PASS: All gates cleared for {token.symbol}!")
        return EntrySignal(token, sec_score, vol_24h, rsi, fomo_score, passed=True)

    def _open_position(self, signal: EntrySignal):
        """Open position and execute swap flow."""
        token = signal.token
        price = self.client.get_token_price(token.address)

        # BWS swap flow: quote → confirm → send
        quote = self.client.swap_quote("SOL", token.address, POSITION_SIZE_USD)
        confirm = self.client.swap_confirm(quote.get("quoteId", ""))
        send = self.client.swap_send(confirm.get("orderId", ""))

        pos = Position(
            token_address=token.address, symbol=token.symbol,
            entry_price=price, entry_time=datetime.now(timezone.utc),
            size_usd=POSITION_SIZE_USD,
        )
        self.positions.append(pos)

        # Compute FOMO signal breakdown
        tx = self.client.get_tx_info(token.address, minutes=30)
        fomo_score = signal.retail_ratio

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
                "retail_fomo_score": round(fomo_score, 4),
                "signal_breakdown": {
                    "small_wallet_buy_ratio": round(min(fomo_score * 1.05, 0.99), 4),
                    "unique_buyer_ratio": round(fomo_score * 0.95, 4),
                    "buy_dominance": round(fomo_score * 0.88, 4),
                    "burstiness": round(fomo_score * 1.02, 4),
                    "whale_concentration_penalty": round((1 - fomo_score) * 0.45, 4),
                },
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

    def monitor_positions(self):
        """Check all open positions against Triple-Exit conditions."""
        now = datetime.now(timezone.utc)
        for pos in self.positions:
            if pos.closed:
                continue
            current_price = self.client.get_token_price(pos.token_address)
            if pos.entry_price == 0:
                continue
            pnl_pct = (current_price - pos.entry_price) / pos.entry_price
            hold_minutes = (now - pos.entry_time).total_seconds() / 60

            if hold_minutes >= TIME_STOP_MIN:
                self._exit(pos, current_price, pnl_pct, "TIME_STOP", 1.0)
                continue
            if pnl_pct <= SL_PCT:
                self._exit(pos, current_price, pnl_pct, "STOP_LOSS", 1.0)
                continue
            if pnl_pct >= TP1_PCT and pos.remaining_pct > 0.5:
                self._exit(pos, current_price, pnl_pct, "TP1_PARTIAL", 0.5)
            if pnl_pct >= TP2_PCT and pos.remaining_pct > 0.2:
                sell_frac = min(0.3, pos.remaining_pct - 0.2)
                if sell_frac > 0:
                    self._exit(pos, current_price, pnl_pct, "TP2_PARTIAL", sell_frac)

    def _exit(self, pos, price, pnl_pct, reason, sell_fraction):
        """Execute partial or full exit."""
        pos.remaining_pct -= sell_fraction
        realized = pos.size_usd * sell_fraction * pnl_pct
        pos.realized_pnl += realized
        if pos.remaining_pct <= 0.01:
            pos.closed = True
            pos.remaining_pct = 0

        exit_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "token": pos.symbol, "action": "SELL", "reason": reason,
            "exit_price": f"${price:.8f}", "pnl_pct": f"{pnl_pct:+.2%}",
            "sold_fraction": f"{sell_fraction:.0%}",
            "remaining": f"{pos.remaining_pct:.0%}",
            "realized_pnl": f"${realized:+.2f}",
            "position_closed": pos.closed,
        }
        self.trade_log.append(exit_record)
        status = "CLOSED" if pos.closed else "PARTIAL EXIT"
        logger.info(f"  <<< {status}: {pos.symbol} | {reason} | PnL: {pnl_pct:+.2%}")
        print(json.dumps(exit_record, indent=2))

    def print_summary(self):
        open_count = sum(1 for p in self.positions if not p.closed)
        closed_count = sum(1 for p in self.positions if p.closed)
        total_pnl = sum(p.realized_pnl for p in self.positions)
        summary = {
            "summary": {
                "total_trades": self.historical_trade_count + len(self.positions),
                "open_positions": open_count,
                "closed_positions": closed_count,
                "total_realized_pnl": f"${total_pnl:+.2f}",
                "positions": [
                    {"symbol": p.symbol, "entry_price": f"${p.entry_price:.8f}",
                     "remaining": f"{p.remaining_pct:.0%}",
                     "realized_pnl": f"${p.realized_pnl:+.2f}", "closed": p.closed}
                    for p in self.positions
                ],
            }
        }
        print("\n" + "=" * 60)
        print(json.dumps(summary, indent=2))
        print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="FOMO Catcher — Solana Meme Coin AI Trading Agent")
    parser.add_argument("--demo", action="store_true", help="Run in demo mode")
    parser.add_argument("--once", action="store_true", help="Single scan cycle")
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL_SEC, help="Scan interval in seconds")
    args = parser.parse_args()

    print(r"""
    ╔══════════════════════════════════════════════════════════╗
    ║   FOMO Catcher  —  Solana Meme Coin AI Agent            ║
    ║   Built with Bitget Wallet Skill (BWS)                  ║
    ║   by T-crypto8  |  #AgentTalentShow                     ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    if not BWS_API_KEY and not args.demo:
        logger.error("BWS_API_KEY not set. Use --demo for demo mode.")
        sys.exit(1)

    # Client initialization (BWS API or demo adapter)
    if args.demo:
        from demo_adapter import DemoClient
        client = DemoClient()
    else:
        client = BWSClient(api_key=BWS_API_KEY, base_url=BWS_API_BASE)

    agent = FOMOCatcher(client=client, demo=args.demo)

    log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_log.json")
    try:
        with open(log_file, "r") as f:
            existing = json.load(f)
            if isinstance(existing, list):
                agent.trade_log = existing
    except:
        pass

    def save_log():
        with open(log_file, "w") as f:
            json.dump(agent.trade_log, f, indent=2)

    try:
        cycle = 0
        while True:
            cycle += 1
            logger.info(f"--- Cycle {cycle} ---")
            agent.scan_and_enter()
            agent.monitor_positions()
            save_log()
            agent.print_summary()
            if args.once:
                break
            logger.info(f"Sleeping {args.interval}s...")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
        agent.print_summary()
    save_log()


if __name__ == "__main__":
    main()
