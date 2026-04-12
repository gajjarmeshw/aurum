---
name: ICT_Strategy_Architect
description: Formalizes the technical logic for ICT sequences (BSL/SSL, FVG, OB) and 12-point confluence scoring.
---

# ICT Strategy Architect Skill

This skill defines the "Brain" of AURUM—the technical logic that identifies high-probability trade setups based on Inner Circle Trader (ICT) concepts.

## Core Modules & Function Signatures

### 1. Indicators: `core/indicators.py`
- `find_fvgs(candles)`: Returns list of `FVG` objects with `high, low, direction, datetime`.
- `detect_zones(candles)`: Detects Order Blocks (`OB`) and Liquidity levels.
- `detect_swings(candles, lookback=5)`: Returns `SwingHigh` and `SwingLow` list.

### 2. Confluence Engine: `core/confluence.py`
- **Method**: `calculate_confluence(indicators, current_price, timeframe)`
- **Scoring Weights (Minute Details)**:
    - `fvg_ob_overlap`: **2.0 pts**
    - `ict_sequence`: **1.5 pts**
    - `h1_bos`: **1.5 pts**
    - `ote_zone` (0.618 - 0.786): **1.0 pts**
    - `killzone_timing`: **1.0 pts**
    - `premium_discount`: **0.5 pts**
    - `atr_normal`: **0.5 pts**
- **Threshold**: **Min 5.0** for London/NY, **Min 8.0** for Asian session.

### 3. State Machine: `core/ict_sequence.py`
- **State Transition**: `Idle -> Sweep -> MSS -> Displacement -> Retracement -> Entry`.
- `validate_sequence(events)`: Returns `ICTGrade(grade, steps_completed, confidence)`.

### 4. Dealing Range: `core/dealing_range.py`
- `calculate_dr(low, high)`: Returns `DR` object with `equilibrium, ote_high, ote_low`.

## The ICT 5-Step Flow
1. **Liquidity Sweep**: BSL or SSL taken on H1/H4.
2. **MSS (Market Structure Shift)**: Price breaks a recent swing on M15.
3. **Displacement**: Strong move creating a Fair Value Gap (FVG).
4. **Return to FVG/OB**: Price retraces into the gap or an Order Block.
5. **Killzone Entry**: Trade is only valid during London or NY Open.

## Confluence Scoring (Max 12.0)
- **FVG + OB Overlap**: 2.0 pts.
- **ICT Sequence Match**: 1.5 pts.
- **H1 BOS**: 1.5 pts.
- **OTE Zone**: 1.0 pts.
- **Killzone Timing**: 1.0 pts.
- (See `config.py` for full weighting)

## Usage for AI Agents
When modifying the strategy, agents must consult `config.py` for thresholds and `ict_sequence.py` for the state machine logic.
