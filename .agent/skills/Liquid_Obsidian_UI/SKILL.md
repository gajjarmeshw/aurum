---
name: Liquid_Obsidian_UI
description: Documents the AURUM Pro design system, SSE event mapping, and charting overlays.
---

# Liquid Obsidian UI Skill

This skill defines the visual identity and front-end logic for the AURUM Pro Trading Terminal.

## Front-End Technical Details

### 1. Design System Tokens: `static/style.css`
- **Amber**: `--amber: #ff8c00;`
- **Neon Green**: `--neon-green: #39ff14;`
- **Teal**: `--teal: #00e5c8;`
- **Background**: `--bg: #040608;`
- **Surface**: `--card-bg: #090d14;`

### 2. Chart Engine: `static/charts.js`
- **Library**: TradingView Lightweight Charts v4.1.3.
- **Overlays**:
    - `FVG`: Rendered as `createPriceLine` pairs with semi-transparent backgrounds.
    - `OB`: Rendered as solid border lines.
    - `Markers`: `arrowUp/arrowDown` for swing highs/lows and entries.
- **Auto-Size**: Uses `ResizeObserver` on `#chart-container` to set `width`/`height`.

### 3. UI Controller: `static/sse.js`
- **Main Class**: `GoldAnalystSSE`.
- **Initialization**: `this.charts = new GoldCharts('chart-container')`.
- **Timeframe Switching**: `switchMainTimeframe(tf)` updates CSS classes on `tf-btn` and calls `charts.switchTimeframe(tf)`.

## SSE Event Mapping
- `tick`: Real-time price update.
- `candle_close`: Updates the chart with a new H4/H1/M15/M5 bar.
- `indicator_update`: Refreshes ICT zones (FVG, OB).
- `trade_signal`: Updates the Confluence Edge score.
- `alert`: Displays a toast notification in the UI.

## Chart Interactivity
- **Timeframe Switching**: Handled by `switchMainTimeframe(tf)` in `sse.js`.
- **Overlays**: `GoldCharts` renders semi-transparent FVG zones and Order Blocks.
- **Resize**: `ResizeObserver` ensures the chart fills its card container reliably on mobile.

## PWA Features (AURUM Pro)
- **Manifest**: `static/manifest.json`.
- **Service Worker**: `sw.js` (Enables standalone "Add to Home Screen" mode).
- **Safe Area**: CSS `env(safe-area-inset-top)` handles iPhone notches.
