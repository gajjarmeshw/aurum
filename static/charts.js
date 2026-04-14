/* ═══════════════════════════════════════════════════════
   AURUM — Live Chart Engine (lightweight-charts v4)
   Candles + ICT overlays: FVG, OB, BSL/SSL, DR, Swings
   ═══════════════════════════════════════════════════════ */

'use strict';

class AurumChart {
    constructor(containerId) {
        this.containerId = containerId;
        this.chart        = null;
        this.candleSeries = null;
        this.tf           = 'M5';
        this._overlayRefs = [];   // price lines / series to remove on redraw
        this._lastCandle  = null; // for live tick updates
        this._ready       = false;
    }

    init() {
        const container = document.getElementById(this.containerId);
        if (!container || typeof LightweightCharts === 'undefined') return;

        this.chart = LightweightCharts.createChart(container, {
            layout: {
                background: { color: '#07060f' },
                textColor:  '#6b7280',
                fontFamily: "'Space Mono', monospace",
                fontSize:   11,
            },
            grid: {
                vertLines:  { color: 'rgba(255,255,255,0.03)' },
                horzLines:  { color: 'rgba(255,255,255,0.03)' },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: { color: 'rgba(124,58,237,0.5)', labelBackgroundColor: '#7c3aed' },
                horzLine: { color: 'rgba(124,58,237,0.5)', labelBackgroundColor: '#7c3aed' },
            },
            rightPriceScale: {
                borderColor:     'rgba(255,255,255,0.05)',
                scaleMarginTop:  0.1,
                scaleMarginBottom: 0.1,
            },
            timeScale: {
                borderColor:         'rgba(255,255,255,0.05)',
                timeVisible:         true,
                secondsVisible:      false,
                rightOffset:         10,
                barSpacing:          8,
                fixLeftEdge:         false,
                lockVisibleTimeRangeOnResize: true,
            },
            handleScroll:  { mouseWheel: true, pressedMouseMove: true },
            handleScale:   { mouseWheel: true, pinch: true },
        });

        this.candleSeries = this.chart.addCandlestickSeries({
            upColor:          '#00ffa3',
            downColor:        '#ff2d6b',
            borderUpColor:    '#00ffa3',
            borderDownColor:  '#ff2d6b',
            wickUpColor:      'rgba(0,255,163,0.5)',
            wickDownColor:    'rgba(255,45,107,0.5)',
        });

        // Resize observer
        new ResizeObserver(() => {
            if (this.chart && container.clientWidth > 0) {
                this.chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
            }
        }).observe(container);

        this._ready = true;
    }

    async loadTF(tf) {
        if (!this._ready) return;
        this.tf = tf;

        // Update TF button states
        document.querySelectorAll('.chart-tf-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.tf === tf);
        });

        const chip = document.getElementById('chart-loading-chip');
        if (chip) { chip.style.display = 'inline-flex'; chip.textContent = 'LOADING…'; }

        try {
            const resp = await fetch(`/api/candles/${tf}`);
            const data = await resp.json();

            // Set candles
            const sorted = (data.candles || []).sort((a, b) => a.time - b.time);
            this.candleSeries.setData(sorted);
            if (sorted.length) this._lastCandle = sorted[sorted.length - 1];

            // Clear old overlays
            this._clearOverlays();

            // Draw ICT overlays
            this._drawOverlays(data.overlays || {});

            // Fit visible range to last 100 bars
            this.chart.timeScale().scrollToPosition(0, false);

            // Apply cached overlays immediately after load
            if (window.analyst) window.analyst._refreshChartOverlays();

            if (chip) chip.style.display = 'none';
        } catch (e) {
            console.error('[Chart] Load failed:', e);
            if (chip) { chip.textContent = 'ERROR'; }
        }
    }

    // ── Live tick update ───────────────────────────────────
    onTick(price, timestamp) {
        if (!this._ready || !this.candleSeries || !this._lastCandle) return;

        const tfSeconds = { M5: 300, M15: 900, H1: 3600, H4: 14400 };
        const barSec    = tfSeconds[this.tf] || 300;
        const barStart  = Math.floor(timestamp / barSec) * barSec;

        if (barStart === this._lastCandle.time) {
            // Update current bar
            this._lastCandle = {
                ...this._lastCandle,
                high:  Math.max(this._lastCandle.high, price),
                low:   Math.min(this._lastCandle.low,  price),
                close: price,
            };
        } else if (barStart > this._lastCandle.time) {
            // New bar
            this._lastCandle = {
                time:  barStart,
                open:  price,
                high:  price,
                low:   price,
                close: price,
            };
        }
        this.candleSeries.update(this._lastCandle);
    }

    // ── Overlay drawing ───────────────────────────────────
    _drawOverlays(ov) {
        const tf = this.tf;

        // ── Dealing Range ──────────────────────────────
        if (ov.dealing_range) {
            const dr = ov.dealing_range;
            if (dr.high) this._priceLine(dr.high, '#7c3aed', 'R.HIGH', 'dashed');
            if (dr.low)  this._priceLine(dr.low,  '#7c3aed', 'R.LOW',  'dashed');
            if (dr.eq)   this._priceLine(dr.eq,   'rgba(124,58,237,0.4)', 'EQ', 'dotted');
            if (dr.ote_high) this._priceLine(dr.ote_high, 'rgba(245,158,11,0.6)', 'OTE.H', 'dashed');
            if (dr.ote_low)  this._priceLine(dr.ote_low,  'rgba(245,158,11,0.6)', 'OTE.L', 'dashed');
        }

        // ── Liquidity Pools (BSL/SSL) — only unswept ──
        for (const pool of (ov.liquidity_pools || [])) {
            if (!pool.price || pool.swept) continue;
            const color = pool.type === 'BSL' ? '#00ffa3' : '#ff2d6b';
            this._priceLine(pool.price, color, pool.type, 'dashed');
        }

        // ── FVGs — pick correct TF list, only unfilled, last 5 ──
        const fvgList = tf === 'H4' ? [] :
                        tf === 'H1' ? (ov.fvgs_h1 || []) :
                        tf === 'M15' ? (ov.fvgs_m15 || []) :
                        (ov.fvgs_m5 || ov.fvgs_m15 || []);

        for (const fvg of fvgList.filter(f => !f.filled).slice(-5)) {
            const bull  = fvg.direction === 'bullish';
            const color = bull ? 'rgba(0,255,163,0.7)' : 'rgba(255,45,107,0.7)';
            this._band(fvg.high, fvg.low, null, color, bull ? 'FVG▲' : 'FVG▼');
        }

        // ── OBs — pick correct TF list, only unmitigated, last 3 ──
        const obList = tf === 'H4' ? (ov.obs_h4 || []) :
                       tf === 'H1' ? (ov.obs_h1 || []) :
                       tf === 'M15' ? (ov.obs_m15 || []) :
                       (ov.obs_m5 || ov.obs_m15 || []);

        for (const ob of obList.filter(o => !o.mitigated).slice(-3)) {
            const bull  = ob.direction === 'bullish';
            const color = bull ? 'rgba(0,255,163,0.9)' : 'rgba(255,45,107,0.9)';
            this._band(ob.high, ob.low, null, color, bull ? 'OB▲' : 'OB▼');
        }

        // ── Swing points — only last 3 highs + 3 lows ──
        if (tf === 'H1' || tf === 'H4') {
            for (const s of (ov.swing_highs_h1 || []).slice(-3)) {
                if (s.price) this._priceLine(s.price, 'rgba(34,211,238,0.35)', 'SH', 'dotted');
            }
            for (const s of (ov.swing_lows_h1 || []).slice(-3)) {
                if (s.price) this._priceLine(s.price, 'rgba(245,158,11,0.35)', 'SL', 'dotted');
            }
        }
    }

    _priceLine(price, color, title, style = 'solid') {
        const lineStyle = {
            solid:  LightweightCharts.LineStyle.Solid,
            dashed: LightweightCharts.LineStyle.Dashed,
            dotted: LightweightCharts.LineStyle.Dotted,
        }[style] || LightweightCharts.LineStyle.Dashed;

        const line = this.candleSeries.createPriceLine({
            price,
            color,
            lineWidth:   1,
            lineStyle,
            axisLabelVisible: true,
            title,
        });
        this._overlayRefs.push({ type: 'priceLine', ref: line });
    }

    // Draw a band as two solid price lines (top + bottom) — no fill area
    _band(high, low, _bg, borderColor, label) {
        this._priceLine(high, borderColor, label, 'solid');
        this._priceLine(low,  borderColor, '',     'solid');
    }

    _clearOverlays() {
        for (const item of this._overlayRefs) {
            try {
                if (item.type === 'priceLine') {
                    this.candleSeries.removePriceLine(item.ref);
                } else if (item.type === 'series') {
                    this.chart.removeSeries(item.ref);
                }
            } catch (_) {}
        }
        this._overlayRefs = [];
    }

    // Called on indicators update — redraw overlays without reloading candles
    refreshOverlays(overlays) {
        this._clearOverlays();
        this._drawOverlays(overlays);
    }
}

// ── Singleton, mounted when CHARTS tab first opens ──────
window.aurumChart = null;

function initChartTab() {
    if (window.aurumChart) return; // already initialised
    window.aurumChart = new AurumChart('chart-container');
    window.aurumChart.init();
    window.aurumChart.loadTF('M5');
}

function chartSwitchTF(tf) {
    if (!window.aurumChart) return;
    window.aurumChart.loadTF(tf);
}
