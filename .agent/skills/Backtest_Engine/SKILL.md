---
name: Backtest_Engine
description: Automates the AURUM historical data fetching, trade simulation, and markdown reporting lifecycle.
---

# Backtest Engine Skill

This skill manages the validation of trading strategies by fetching historical XAUUSD data, running the simulation engine, and generating performance reports.

## Core Components & Technical Details

### 1. Data Fetcher: `backtest/historical_fetch.py`
- **Method**: `fetch_historical_data(symbol, interval, output_file)`
- **Defaults**: Fetches `XAU/USD` for `15min`, `1h`, and `4h` by default (last 5000 intervals).
- **Execution**: `python backtest/historical_fetch.py`
- **CSV Schema**: `datetime, open, high, low, close, volume` (Datetime format: `YYYY-MM-DD HH:MM:SS`)

### 2. Simulator: `backtest/trade_simulator.py`
- **Inputs**: Reads CSVs from `backtest/data/`.
- **Logic**: Iterates through the `1h` CSV as the "Anchor" and checks `M15` / `M5` for confirmations.
- **Reporting**: Calls `generate_markdow_report(trades, stats)` to produce the output.

## Output Structure
Generates a markdown file named `GOLD_TRADE_[DATE].md` containing:
- **Win Rate**: Calculated as `wins / total_trades`.
- **Profit Factor**: `total_gains / abs(total_losses)`.
- **Trade List**: Table with `Entry, Exit, Result ($), Confluence Score, Duration`.

## Data Locations
- **CSV Data**: `backtest/data/`
- **Reports**: Root directory (e.g., `GOLD_TRADE_2026-04-05-1852.md`)

## Key Indicators Tested
Matches the settings in `config.py`:
- FVG / OB / Swing Liquidity.
- Killzone Windows (London/NY).
- 12-point Confluence Scoring.
