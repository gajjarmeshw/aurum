# XAUUSD Trade Analyst v4

> EC2-hosted Python app | Real-time gold analysis | Claude-powered trade signals

A self-hosted, always-on trading analysis system for XAUUSD (Gold) using ICT methodology. Runs on AWS EC2, watches the market 24/7, and generates structured reports for Claude analysis.

## Features

- **Dual-Source WebSocket Feed** — Twelve Data (primary) + Finnhub (fallback) with automatic failover
- **Multi-Timeframe Candle Builder** — M5/M15/H1/H4 built from live tick stream
- **ICT Analysis Suite** — ATR, Swing H/L, FVG, Order Blocks, BOS/CHoCH, Liquidity Pools
- **6-Step ICT Sequence Grader** — A+/A/B/None classification
- **12-Point Weighted Confluence Scorer** — Auto-calibrates after 30 trades
- **H4 Dealing Range + OTE Zone** — Fibonacci-based entry zones
- **Psychology Pre-Trade Gate** — 5 questions, hard blocks on revenge/emotional trading
- **Post-Loss Cooldown Engine** — 30min/60min/$50 hard lock
- **Session Manager** — IST killzone windows, status light, countdown timer
- **Macro Context** — DXY, US10Y yield, gold sentiment from free APIs
- **London → NY Handoff** — Auto-generated session bridge
- **Report Generator** — Full `.md` for Claude analysis
- **Dark Terminal Dashboard** — Real-time SSE updates
- **Walk-Forward Backtest** — Historical validation, no future leakage
- **Telegram Alerts** — Setup alerts, edge decay, feed failover
- **Personalized Playbook** — Auto-generated after 50 trades

## Quick Start

```bash
# Clone
git clone https://github.com/gajjarmeshw/aurum.git
cd aurum

# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your API keys

# Run
python main.py
# Dashboard: http://localhost:5000
```

## Required API Keys (all free)

| Service | Purpose | Signup |
|---------|---------|--------|
| [Twelve Data](https://twelvedata.com) | Primary tick feed + DXY | Free tier |
| [Finnhub](https://finnhub.io) | Fallback tick feed | Free tier |
| [NewsAPI](https://newsapi.org) | Gold sentiment | Free tier |
| [Telegram Bot](https://t.me/BotFather) | Trade alerts | Free |

## Architecture

```
┌──────────────────────┐    ┌──────────────────────┐
│   DATA PIPELINE      │    │   WEB SERVER         │
│   (asyncio process)  │    │   (Flask process)    │
│                      │    │                      │
│  WebSocket Feeds     │    │  Dashboard (SSE)     │
│  Candle Builder      │◄──►│  Report Generator    │
│  Indicator Engine    │    │  Psychology Gate      │
│  Confluence Scorer   │    │  Journal API         │
│                      │    │  Backtest UI         │
└──────────────────────┘    └──────────────────────┘
         ▲                           │
         │      EventBus             │
         └───────(Queue)─────────────┘

         Telegram ◄── Alerts (8+/12 in killzone)
```

## Trading Rules

- **Account**: QTFunded $10,000 Instant
- **Instrument**: XAUUSD only
- **Sessions**: London (1:30–4:30 PM IST) + NY (6:30–11:30 PM IST)
- **Max trades**: 2/day (different sessions + levels)
- **Risk**: $25 max per trade (0.03 lots)
- **Target**: $300/week → scale to $25k account

## Tech Stack

Python 3.11 · asyncio · Flask · WebSockets · Pandas · TradingView Charts (free)

## License

Private — personal trading system.
