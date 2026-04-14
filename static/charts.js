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

            // Fit to last 80 bars
            this.chart.timeScale().scrollToPosition(0, false);

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

        // Dealing Range — dashed lines
        if (ov.dealing_range) {
            const dr = ov.dealing_range;
            if (dr.high) this._priceLine(dr.high, '#7c3aed', '──── RANGE HIGH', 'dashed');
            if (dr.low)  this._priceLine(dr.low,  '#7c3aed', '──── RANGE LOW',  'dashed');
            if (dr.eq)   this._priceLine(dr.eq,   'rgba(124,58,237,0.5)', 'EQ', 'dotted');
            if (dr.ote_high && dr.ote_low) {
                this._band(dr.ote_high, dr.ote_low, 'rgba(245,158,11,0.06)', 'rgba(245,158,11,0.4)', 'OTE');
            }
        }

        // Liquidity pools (BSL / SSL)
        for (const pool of (ov.liquidity_pools || [])) {
            if (!pool.price) continue;
            const isBSL   = pool.type === 'BSL';
            const swept   = pool.swept;
            const color   = swept ? 'rgba(107,114,128,0.5)' : (isBSL ? '#00ffa3' : '#ff2d6b');
            const label   = `${pool.type}${swept ? ' ✓' : ''}`;
            this._priceLine(pool.price, color, label, 'dashed');
        }

        // FVGs
        const fvgs = tf === 'H1' ? ov.fvgs_h1 : (tf === 'M15' || tf === 'M5' ? ov.fvgs_m15 : []);
        for (const fvg of (fvgs || [])) {
            if (!fvg.high || !fvg.low || fvg.filled) continue;
            const bull   = fvg.direction === 'bullish';
            const bg     = bull ? 'rgba(0,255,163,0.06)' : 'rgba(255,45,107,0.06)';
            const border = bull ? 'rgba(0,255,163,0.35)' : 'rgba(255,45,107,0.35)';
            this._band(fvg.high, fvg.low, bg, border, bull ? 'FVG ▲' : 'FVG ▼');
        }

        // OBs
        const obs = tf === 'H1' ? ov.obs_h1 : ov.obs_m15;
        for (const ob of (obs || [])) {
            if (!ob.high || !ob.low || ob.mitigated) continue;
            const bull   = ob.direction === 'bullish';
            const bg     = bull ? 'rgba(0,255,163,0.04)' : 'rgba(255,45,107,0.04)';
            const border = bull ? 'rgba(0,255,163,0.5)' : 'rgba(255,45,107,0.5)';
            this._band(ob.high, ob.low, bg, border, bull ? 'OB ▲' : 'OB ▼');
        }

        // H1 Swing Highs / Lows
        if (tf === 'H1' || tf === 'H4') {
            for (const s of (ov.swing_highs_h1 || [])) {
                if (s.price) this._priceLine(s.price, 'rgba(34,211,238,0.4)', 'SH', 'dotted');
            }
            for (const s of (ov.swing_lows_h1 || [])) {
                if (s.price) this._priceLine(s.price, 'rgba(245,158,11,0.4)', 'SL', 'dotted');
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

    // Simulate a band with two price lines + a filled area series
    _band(high, low, bg, borderColor, label) {
        // Top line
        this._priceLine(high, borderColor, label, 'solid');
        // Bottom line
        this._priceLine(low,  borderColor, '',     'solid');

        // Fill band using area series
        const area = this.chart.addAreaSeries({
            topColor:        bg,
            bottomColor:     bg,
            lineColor:       'transparent',
            lineWidth:       0,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
        });
        // Area series needs time data — inject as two points spanning the chart
        const now   = Math.floor(Date.now() / 1000);
        const start = now - 200 * 300; // 200 bars back
        area.setData([
            { time: start, value: high },
            { time: now,   value: high },
        ]);
        // Overlay the low band
        const area2 = this.chart.addAreaSeries({
            topColor:        'transparent',
            bottomColor:     bg,
            lineColor:       'transparent',
            lineWidth:       0,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
            baseValue:       { type: 'price', price: low },
        });
        area2.setData([
            { time: start, value: low },
            { time: now,   value: low },
        ]);

        this._overlayRefs.push({ type: 'series', ref: area });
        this._overlayRefs.push({ type: 'series', ref: area2 });
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
