# FOMO Catcher

**Solana Meme Coin AI Trading Agent — Detect retail FOMO before the crowd, enter with rules, and exit before the crash.**

by T-crypto8

Built with **Bitget Wallet Skill (BWS)** for the **Solana Agent Economy Hackathon #AgentTalentShow**.

---

## What It Does

**FOMO Catcher** is an autonomous trading agent for Solana meme coins.

Its job is simple:

1. **Scan** the market for fast-moving meme coins
2. **Filter** out weak, unsafe, or whale-driven moves
3. **Detect real retail participation** using on-chain transaction structure
4. **Enter only when momentum is strong but not exhausted**
5. **Manage exits automatically** with disciplined multi-stage risk control

Most meme coin bots react to **price** and **volume** only.
FOMO Catcher goes one level deeper: it asks **who is buying**.

The core hypothesis is:

> The most explosive meme coin moves are often driven by **many small wallets buying in clusters**, not by a few whales pushing price temporarily.

That pattern is what we call **Retail FOMO**.

---

## Why This Agent Is Different

Most trading agents look at:
- price momentum
- volume spikes
- liquidity
- RSI or breakout signals

FOMO Catcher also analyzes **transaction composition** using BWS `tx_info`.

It tries to distinguish:

- **organic retail momentum**
  from
- **whale-led or manipulated movement**

This is important in meme coins, where a chart can look bullish even when the move is fragile.

So this agent is not just asking:

**"Is price going up?"**

It is asking:

**"Is this move being carried by the crowd in a healthy way, or by a few large players?"**

---

## Architecture

```text
┌─────────────────────────────────────────────────────┐
│                    FOMO Catcher                     │
│                                                     │
│  ┌──────────┐   ┌──────────┐   ┌───────────────┐   │
│  │ Scanner  │──▶│ Analyzer │──▶│ Position Mgr  │   │
│  │          │   │          │   │               │   │
│  │ rankings │   │ security │   │ Triple-Exit   │   │
│  │          │   │ liquidity│   │ TP1: +15%     │   │
│  │          │   │ kline    │   │ TP2: +30%     │   │
│  │          │   │ tx_info  │   │ SL:  -8%      │   │
│  └──────────┘   └──────────┘   │ Time: 30 min  │   │
│                                 └───────────────┘   │
│                        │                            │
│                        ▼                            │
│              ┌──────────────────┐                   │
│              │  BWS Swap Flow   │                   │
│              │ quote → confirm  │                   │
│              │ → send           │                   │
│              └──────────────────┘                   │
└─────────────────────────────────────────────────────┘
                         │
                         ▼
            ┌────────────────────────────┐
            │   Bitget Wallet Skill API  │
            │       Solana On-Chain      │
            └────────────────────────────┘
```

---

## BWS Endpoints Used

| Endpoint                 | Purpose                                           |
| ------------------------ | ------------------------------------------------- |
| `rankings`               | Find top gaining Solana tokens                    |
| `security`               | Filter unsafe or suspicious tokens                |
| `liquidity`              | Check tradability and minimum liquidity/volume    |
| `kline`                  | Calculate RSI and short-term momentum state       |
| `tx_info`                | Analyze wallet behavior and Retail FOMO structure |
| `token_price`            | Track live position PnL                           |
| `quote / confirm / send` | Execute swap flow                                 |

This project is designed around the **full decision-to-execution loop**, not just signal generation.

---

## Trading Strategy: Retail FOMO Scalper

### Entry — 5-Gate Filter

A token must pass **all 5 gates**:

1. **Top Gainer**
   * Must rank in the top 5 by **1h gain**
   * Source: `rankings`

2. **Security Score**
   * Must have **security ≥ 70**
   * Reject obvious honeypots / blacklisted contracts / suspicious tokens
   * Source: `security`

3. **Liquidity / Volume**
   * Must have **24h liquidity or volume > $50K**
   * Avoid thin pools and untradeable spikes
   * Source: `liquidity`

4. **Momentum Quality**
   * **5m RSI must be between 45 and 65**
   * Avoid late overbought chase entries
   * Avoid weak rebounds with no continuation
   * Source: `kline`

5. **Retail FOMO Signal**
   * Retail FOMO score must be **> 0.70**
   * Source: `tx_info`

---

## Retail FOMO Signal — How It Works

This is the core feature of the agent.

Instead of using only candle data, FOMO Catcher analyzes recent on-chain transaction behavior and computes a **Retail FOMO Score**.

### Intuition

We want to see:

* many **small buy transactions**
* from **many distinct wallets**
* arriving in a **short time window**
* without a few large wallets dominating flow

That is a stronger signal of real crowd participation than price alone.

### Example Heuristic

For the most recent transaction window, the agent estimates:

* **Small Wallet Buy Ratio** — Share of buy transactions coming from wallets below a chosen size threshold
* **Unique Buyer Ratio** — Number of distinct buyers relative to total recent participants
* **Buy Dominance** — Ratio of buys vs sells in the recent transaction set
* **Whale Concentration Penalty** — Penalty if a small number of large wallets dominate volume
* **Burstiness / Momentum Density** — Reward if many retail buys arrive close together in time

### Example Scoring Formula

```text
Retail FOMO Score =
  0.30 * SmallWalletBuyRatio
+ 0.25 * UniqueBuyerRatio
+ 0.20 * BuyDominance
+ 0.15 * Burstiness
- 0.10 * WhaleConcentration
```

Then the score is normalized to the range **0.00–1.00**.

### Why This Matters

Two tokens can both be up +30%.

But one may be driven by:
* 3 large wallets
* low participation breadth
* fragile momentum

While the other may be driven by:
* dozens of small buyers
* broad participation
* strong social/retail follow-through

FOMO Catcher prefers the second structure.

---

## Why We Call It an AI Agent

This project is not just a static screener.

It behaves like an **agent** because it:

* **observes** live market state
* **interprets** transaction structure
* **decides** whether momentum is healthy or dangerous
* **acts** through the BWS swap flow
* **manages** the position after entry
* **explains** each decision through structured output

The "AI" layer here is the **behavioral interpretation of on-chain flow**, not just raw threshold checking.

In future versions, the same framework can support:

* adaptive weighting of Retail FOMO sub-signals
* regime-aware thresholds
* post-trade learning from win/loss outcomes
* natural-language trade explanations

---

## Exit Logic — Triple-Exit Risk Management

Meme coins move fast, so exits matter more than entries.

### Exit Plan

| Level     | Trigger | Action    |
| --------- | ------: | --------- |
| TP1       |    +15% | Sell 50%  |
| TP2       |    +30% | Sell 30%  |
| Stop Loss |     -8% | Full exit |
| Time Stop |  30 min | Full exit |

### Why This Exit Structure

This exit design is meant to solve a classic meme coin problem:

* full take-profit exits often cut winners too early
* no take-profit exits often round-trip gains
* wide stops can be fatal in high-volatility tokens

So the agent:

* **locks in gains early**
* **keeps some upside exposure**
* **cuts downside fast**
* **avoids overstaying hype trades**

---

## Example Decision Output

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
    "retail_fomo_score": 0.7312,
    "signal_breakdown": {
      "small_wallet_buy_ratio": 0.81,
      "unique_buyer_ratio": 0.74,
      "buy_dominance": 0.69,
      "burstiness": 0.77,
      "whale_concentration_penalty": 0.18
    }
  },
  "position_size": "$100",
  "exit_plan": {
    "tp1": "+15% (sell 50%)",
    "tp2": "+30% (sell 30%)",
    "sl": "-8% (full exit)",
    "time_stop": "30min"
  }
}
```

This makes the agent's decisions **auditable**, **explainable**, and easy to demo.

---

## Safety and Risk Filters

Because Solana meme coins are noisy and dangerous, the agent is intentionally conservative.

It avoids:

* unsafe tokens with low security scores
* low-liquidity traps
* exhausted RSI conditions
* whale-dominated moves that may collapse quickly

This does **not** eliminate risk.
It is a **risk-reduction framework**, not a guarantee.

---

## Demo / Live Modes

### Demo Mode

Uses mock data and runs safely without execution.

```bash
python agent.py --mock
python agent.py --mock --once
python agent.py --mock --interval 30
```

### Live Mode

Uses BWS API and live-ready execution flow.

```bash
export BWS_API_KEY="your-api-key-here"
export BWS_API_BASE="https://api.bitgetwallet.com/wallet-skill/v1"

python agent.py
```

---

## Project Structure

```text
fomo-catcher/
├── agent.py          # Main agent logic
├── dashboard.html    # Live trading dashboard with real-time prices
├── README.md         # Project explanation
└── trade_log.json    # Generated trade history
```

---

## Tech Stack

* **Language:** Python 3.10+ (stdlib only)
* **Chain:** Solana
* **Data / Execution:** Bitget Wallet Skill (BWS)
* **Core Strategy:** Retail FOMO Detection + Triple-Exit Scalping
* **Mode:** Demo / live-ready execution flow

---

## What Makes This Hackathon-Relevant

### 1. Real Agent Behavior
Not just analytics, but **scan → reason → execute → manage**

### 2. Deep BWS Integration
Uses multiple BWS endpoints across discovery, filtering, analysis, monitoring, and execution

### 3. A Novel Trading Lens
Instead of following whales, it detects **retail-led momentum structure**

---

## Future Improvements

* dynamic threshold tuning by market regime
* backtesting / replay mode on historical tx windows
* smarter wallet clustering
* stronger anti-manipulation filters
* LLM-generated trade commentary
* portfolio-level risk caps across multiple meme coin positions

---

## Disclaimer

This project is for **hackathon/demo purposes** and does not guarantee profit.
Meme coin trading is highly speculative and risky.
Always use paper trading or limited capital first.

---

*FOMO Catcher by T-crypto8 — detect the herd, ride the wave, leave before the cliff.*
