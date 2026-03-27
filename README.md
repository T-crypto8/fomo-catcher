# FOMO Catcher

**Solana Meme Coin AI Trading Agent — Detecting retail FOMO before the crowd, and knowing when to leave.**

*by T-crypto8*

Built with [Bitget Wallet Skill (BWS)](https://github.com/bitget-wallet-ai-lab/bitget-wallet-skill) for the **Solana Agent Economy Hackathon #AgentTalentShow**.

---

## What It Does

Retail FOMO Scalper is an autonomous AI trading agent that identifies Solana meme coins experiencing genuine retail buying momentum — not whale manipulation — and executes a disciplined scalping strategy with triple-exit risk management.

**Key Insight:** On meme coins, the strongest pumps are driven by organic retail FOMO (many small wallets buying), not whale accumulation. By analyzing on-chain transaction patterns via BWS's `tx_info` endpoint, we detect this signal before the chart reflects it.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                 Retail FOMO Scalper                  │
│                                                     │
│  ┌──────────┐   ┌──────────┐   ┌───────────────┐   │
│  │  Scanner  │──▶│ Analyzer │──▶│ Position Mgr  │   │
│  │          │   │          │   │               │   │
│  │ rankings │   │ security │   │ Triple-Exit   │   │
│  │ (top     │   │ liquidity│   │ TP1: +15%/50% │   │
│  │  gainers)│   │ kline/RSI│   │ TP2: +30%/30% │   │
│  │          │   │ tx_info  │   │ SL:  -8%      │   │
│  └──────────┘   └──────────┘   │ Time: 30min   │   │
│                                 └───────────────┘   │
│                        │                            │
│                        ▼                            │
│              ┌──────────────────┐                   │
│              │  BWS Swap Flow   │                   │
│              │ quote → confirm  │                   │
│              │ → makeOrder/send │                   │
│              └──────────────────┘                   │
└─────────────────────────────────────────────────────┘
                         │
                         ▼
            ┌──────────────────────┐
            │  Bitget Wallet Skill │
            │       (BWS API)      │
            │    Solana On-Chain   │
            └──────────────────────┘
```

---

## BWS API Endpoints Used

| Endpoint | Purpose |
|----------|---------|
| `rankings` (topGainers) | Find top 5 tokens by 1h gain |
| `security` | Token security audit (honeypot, blacklist) |
| `liquidity` | 24h volume & pool liquidity check |
| `kline` (5m) | Candlestick data for RSI calculation |
| `tx_info` | **On-chain tx analysis — Retail FOMO detection** |
| `token_price` | Real-time USD price for position tracking |
| `quote` / `confirm` / `send` | Swap execution flow (demo: log only) |

> **Note:** BWS API endpoint URLs and response schemas are based on the public BWS documentation. If the actual API differs, the code may need minor adjustments to field names. The mock mode (`--mock`) works independently of the live API.

---

## Trading Strategy: "Retail FOMO Scalper"

### Entry — 5-Gate Filter

Every candidate must pass ALL gates:

1. **Top Gainer** — Token must be in the top 5 by 1h gain (from `rankings`)
2. **Security ≥ 70** — No honeypots or blacklisted contracts (from `security`)
3. **Liquidity > $50K** — 24h trading volume must exceed $50K (from `liquidity`)
4. **RSI 45–65** — Not overbought or oversold on the 5m chart (from `kline`)
5. **Retail FOMO Signal > 70%** — Small-wallet transactions must dominate recent activity (from `tx_info`)

### Exit — Triple-Exit Strategy

| Level | Trigger | Action |
|-------|---------|--------|
| TP1 | +15% | Sell 50% of position |
| TP2 | +30% | Sell 30% of position |
| Stop Loss | -8% | Full exit |
| Time Stop | 30 min | Full exit |

This layered exit captures quick scalps while letting winners run, with strict downside protection.

---

## Differentiation

1. **Retail FOMO Detection via `tx_info`** — Most agents only look at price and volume. We analyze the *composition* of on-chain transactions to distinguish organic retail momentum from whale manipulation.

2. **Triple-Exit Risk Management** — Instead of simple TP/SL, our 3-tier exit maximizes expected value: lock profits early, let a portion ride, and enforce strict time + loss limits.

3. **Full BWS Integration** — Uses 7 BWS endpoints including the complete swap execution flow (quote → confirm → send), demonstrating deep integration with Bitget Wallet Skill.

---

## Setup

### Prerequisites

- Python 3.10+
- A BWS API key (get one from [Bitget Wallet Skill](https://github.com/bitget-wallet-ai-lab/bitget-wallet-skill))

### Installation

```bash
# Clone / navigate to project
cd hackathon/agent-talent-show

# No external dependencies needed — uses Python stdlib only!
# (No pip install required)

# Set your BWS API key (for live mode)
export BWS_API_KEY="your-api-key-here"
export BWS_API_BASE="https://api.bitgetwallet.com/wallet-skill/v1"  # optional, has default
```

### Run

```bash
# Demo mode — simulated data, no API key needed
python agent.py --mock

# Single scan cycle (great for demos)
python agent.py --mock --once

# Live mode (requires BWS_API_KEY)
python agent.py

# Custom scan interval (default: 60s)
python agent.py --mock --interval 30
```

### Output

Each trade decision is logged as structured JSON:

```json
{
  "timestamp": "2026-03-27T13:45:00+00:00",
  "token": "BONK",
  "action": "BUY",
  "entry_reason": {
    "top_gainer_rank": 2,
    "gain_1h_pct": "+42.5%",
    "security_score": 84,
    "liquidity_24h": "$120,000",
    "rsi_5m": 52.3,
    "retail_fomo_signal": 0.7312
  },
  "position_size": "$100 (demo)",
  "exit_plan": {
    "tp1": "+15% (sell 50%)",
    "tp2": "+30% (sell 30%)",
    "sl": "-8% (full exit)",
    "time_stop": "30min"
  }
}
```

Trade logs are saved to `trade_log.json` on exit.

---

## Project Structure

```
agent-talent-show/
├── agent.py        # Main agent — scanner, analyzer, position manager, mock client
├── README.md       # This file
└── trade_log.json  # Generated on run — full trade history
```

---

## Tech Stack

- **Language:** Python 3.10+ (stdlib only, zero dependencies)
- **On-Chain Data:** Bitget Wallet Skill API (Solana)
- **Strategy:** Retail FOMO Detection + Triple-Exit Scalping
- **Mode:** Paper trading (demo) with live-ready swap flow

---

## Hackathon

- **Event:** Solana Agent Economy Hackathon
- **Track:** #AgentTalentShow — Bitget Wallet Prize ($5,000)
- **Built with:** [Bitget Wallet Skill (BWS)](https://github.com/bitget-wallet-ai-lab/bitget-wallet-skill)

---

*FOMO Catcher by T-crypto8 — detect the herd, ride the wave, exit before the crash.*
