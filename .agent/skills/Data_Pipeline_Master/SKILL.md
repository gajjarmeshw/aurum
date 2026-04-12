---
name: Data_Pipeline_Master
description: Manages the dual-source WebSocket feeds, candle building, and feed health orchestration.
---

# Data Pipeline Master Skill

This skill governs the real-time data flow from market providers (Twelve Data, Finnhub) into the AURUM internal state.

## Technical Specifications

### 1. Feed Configuration & Symbols
- **Twelve Data**: `XAU/USD` (Primary). Websocket URL: `wss://ws.twelvedata.com/v1/quotes/price`.
- **Finnhub**: `OANDA:XAU_USD` (Standby). Websocket URL: `wss://ws.finnhub.io`.

### 2. Candle Builder: `pipeline/candle_builder.py`
- **Class**: `Candle` (Properties: `timestamp, open, high, low, close, volume, timeframe, closed`).
- **Logic**: Alignments are `int(ts) // period * period`.
- **Cache**: JSON files in `data/candles/` (e.g., `H1_candles.json`).

### 3. Manager & Health: `pipeline/feed_manager.py`
- **Failover Threshold**: Triggered if `seconds_since_last_tick > 30s`.
- **Events Published to EventBus**:
    - `tick`: `{"price", "timestamp", "source"}`
    - `candle_close`: `{"timeframe", "candle"}`
    - `feed_status`: `{"event": "failover/restored", "from", "to"}`
    - `health`: Full status JSON from `HealthMonitor`.

## Key Logic

### 1. Automated Failover
If the Primary feed (Twelve Data) drops for more than `FEED_TIMEOUT_SECONDS` (30s default in `config.py`), it automatically switches to the Standby feed (Finnhub).

### 2. Candle Seeding
On startup, if the JSON cache is empty, `CandleBuilder` seeds from `backtest/data/*.csv` to provide immediate chart history.

## Troubleshooting
- **429 Error**: Usually means Finnhub is rate-limited (normal in standby).
- **Empty Symbol**: Ensure `config.TWELVE_DATA_SYMBOL` is set to `XAU/USD`.
- **Latency**: Check `HealthMonitor` status via the `health` event on the EventBus.

## Configuration
- `config.py`: Controls reconnect intervals, API keys, and symbol mapping.
