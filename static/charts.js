/**
 * TradingView Lightweight Charts — Live candle rendering with ICT overlays.
 *
 * Features:
 *   - Multi-timeframe (H4/H1/M15/M5) tab switcher
 *   - Live candle updates via SSE
 *   - FVG zones (semi-transparent rectangles)
 *   - Order Block zones
 *   - OTE / Dealing Range shaded zones
 *   - Swing high/low markers
 *   - BOS arrows
 *   - Killzone background tinting
 */

class GoldCharts {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.chart = null;
        this.candleSeries = null;
        this.volumeSeries = null;
        this.activeTimeframe = 'H1';
        this.overlays = { fvg: [], ob: [], ote: null, swings: [], bos: [] };
        this.markers = [];

        if (this.container) {
            this.init();
        }
    }

    async init() {
        // Dynamically load TradingView library
        await this.loadScript('https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js');
        this.createChart();
        this.createTimeframeTabs();
    }

    loadScript(src) {
        return new Promise((resolve, reject) => {
            if (window.LightweightCharts) { resolve(); return; }
            const script = document.createElement('script');
            script.src = src;
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }

    createChart() {
        if (!window.LightweightCharts) return;

        this.chart = LightweightCharts.createChart(this.container, {
            width: this.container.clientWidth,
            height: 420,
            layout: {
                background: { color: '#0a0e17' },
                textColor: '#8899aa',
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11,
            },
            grid: {
                vertLines: { color: '#1e2a3a' },
                horzLines: { color: '#1e2a3a' },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: { color: '#f0b90b', width: 1, style: 2, labelBackgroundColor: '#f0b90b' },
                horzLine: { color: '#f0b90b', width: 1, style: 2, labelBackgroundColor: '#f0b90b' },
            },
            rightPriceScale: {
                borderColor: '#1e2a3a',
                scaleMargins: { top: 0.1, bottom: 0.2 },
            },
            timeScale: {
                borderColor: '#1e2a3a',
                timeVisible: true,
                secondsVisible: false,
            },
        });

        this.candleSeries = this.chart.addCandlestickSeries({
            upColor: '#00c853',
            downColor: '#ff1744',
            borderUpColor: '#00c853',
            borderDownColor: '#ff1744',
            wickUpColor: '#00c853',
            wickDownColor: '#ff1744',
        });

        // Handle resize
        const resizeObserver = new ResizeObserver(entries => {
            for (let entry of entries) {
                this.chart.applyOptions({
                    width: entry.contentRect.width,
                });
            }
        });
        resizeObserver.observe(this.container);
    }

    createTimeframeTabs() {
        const tabContainer = document.createElement('div');
        tabContainer.className = 'chart-tabs';
        tabContainer.innerHTML = ['H4', 'H1', 'M15', 'M5'].map(tf =>
            `<button class="chart-tab ${tf === this.activeTimeframe ? 'active' : ''}" data-tf="${tf}">${tf}</button>`
        ).join('');

        tabContainer.addEventListener('click', (e) => {
            const btn = e.target.closest('.chart-tab');
            if (btn) {
                this.switchTimeframe(btn.dataset.tf);
                tabContainer.querySelectorAll('.chart-tab').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
            }
        });

        this.container.parentNode.insertBefore(tabContainer, this.container);
    }

    switchTimeframe(tf) {
        this.activeTimeframe = tf;
        this.clearOverlays();
        this.fetchCandles(tf);
    }

    async fetchCandles(tf) {
        try {
            const resp = await fetch(`/api/candles/${tf}`);
            const data = await resp.json();
            if (data.candles && data.candles.length > 0) {
                const formatted = data.candles.map(c => ({
                    time: c.timestamp,
                    open: c.open,
                    high: c.high,
                    low: c.low,
                    close: c.close,
                }));
                this.candleSeries.setData(formatted);
                this.chart.timeScale().fitContent();

                // Draw overlays
                if (data.overlays) this.drawOverlays(data.overlays);
            }
        } catch (e) {
            console.warn('Failed to fetch candles:', e);
        }
    }

    updateCandle(candle) {
        if (!this.candleSeries || candle.timeframe !== this.activeTimeframe) return;
        this.candleSeries.update({
            time: candle.timestamp,
            open: candle.open,
            high: candle.high,
            low: candle.low,
            close: candle.close,
        });
    }

    // ─── Overlays ──────────────────────────────────────────

    drawOverlays(overlays) {
        this.clearOverlays();

        // FVG zones — semi-transparent rectangles
        if (overlays.fvgs) {
            overlays.fvgs.forEach(fvg => {
                const color = fvg.direction === 'bullish'
                    ? 'rgba(0, 200, 83, 0.08)'
                    : 'rgba(255, 23, 68, 0.08)';
                const borderColor = fvg.direction === 'bullish'
                    ? 'rgba(0, 200, 83, 0.3)'
                    : 'rgba(255, 23, 68, 0.3)';

                // Use price lines for zone boundaries
                const lineTop = this.candleSeries.createPriceLine({
                    price: fvg.high,
                    color: borderColor,
                    lineWidth: 1,
                    lineStyle: 2,
                    axisLabelVisible: false,
                });
                const lineBot = this.candleSeries.createPriceLine({
                    price: fvg.low,
                    color: borderColor,
                    lineWidth: 1,
                    lineStyle: 2,
                    axisLabelVisible: false,
                });
                this.overlays.fvg.push(lineTop, lineBot);
            });
        }

        // Order Blocks
        if (overlays.obs) {
            overlays.obs.forEach(ob => {
                const color = ob.direction === 'bullish'
                    ? 'rgba(41, 121, 255, 0.3)'
                    : 'rgba(255, 152, 0, 0.3)';
                const lineTop = this.candleSeries.createPriceLine({
                    price: ob.high,
                    color: color,
                    lineWidth: 1,
                    lineStyle: 0,
                    axisLabelVisible: false,
                });
                const lineBot = this.candleSeries.createPriceLine({
                    price: ob.low,
                    color: color,
                    lineWidth: 1,
                    lineStyle: 0,
                    axisLabelVisible: false,
                });
                this.overlays.ob.push(lineTop, lineBot);
            });
        }

        // OTE Zone
        if (overlays.ote) {
            const oteTop = this.candleSeries.createPriceLine({
                price: overlays.ote.high,
                color: 'rgba(240, 185, 11, 0.4)',
                lineWidth: 2,
                lineStyle: 2,
                axisLabelVisible: true,
                title: 'OTE High',
            });
            const oteBot = this.candleSeries.createPriceLine({
                price: overlays.ote.low,
                color: 'rgba(240, 185, 11, 0.4)',
                lineWidth: 2,
                lineStyle: 2,
                axisLabelVisible: true,
                title: 'OTE Low',
            });
            const eq = this.candleSeries.createPriceLine({
                price: overlays.ote.eq,
                color: 'rgba(240, 185, 11, 0.2)',
                lineWidth: 1,
                lineStyle: 1,
                axisLabelVisible: true,
                title: 'EQ',
            });
            this.overlays.ote = [oteTop, oteBot, eq];
        }

        // Swing markers
        if (overlays.swings) {
            const markers = [];
            overlays.swings.forEach(s => {
                markers.push({
                    time: s.timestamp,
                    position: s.type === 'high' ? 'aboveBar' : 'belowBar',
                    color: s.type === 'high' ? '#ff1744' : '#00c853',
                    shape: s.type === 'high' ? 'arrowDown' : 'arrowUp',
                    text: `$${s.price.toFixed(0)}`,
                });
            });
            if (markers.length) {
                markers.sort((a, b) => a.time - b.time);
                this.candleSeries.setMarkers(markers);
                this.markers = markers;
            }
        }

        // BOS arrows
        if (overlays.bos) {
            overlays.bos.forEach(bos => {
                const line = this.candleSeries.createPriceLine({
                    price: bos.price,
                    color: bos.direction === 'bullish' ? '#00c853' : '#ff1744',
                    lineWidth: 2,
                    lineStyle: 0,
                    axisLabelVisible: true,
                    title: `BOS ${bos.direction === 'bullish' ? '↑' : '↓'}`,
                });
                this.overlays.bos.push(line);
            });
        }

        // Dealing Range
        if (overlays.dealing_range) {
            const dr = overlays.dealing_range;
            this.candleSeries.createPriceLine({
                price: dr.high, color: 'rgba(255,23,68,0.3)', lineWidth: 1, lineStyle: 1,
                axisLabelVisible: true, title: 'Range H',
            });
            this.candleSeries.createPriceLine({
                price: dr.low, color: 'rgba(0,200,83,0.3)', lineWidth: 1, lineStyle: 1,
                axisLabelVisible: true, title: 'Range L',
            });
        }

        // Liquidity pools
        if (overlays.liquidity) {
            overlays.liquidity.forEach(pool => {
                this.candleSeries.createPriceLine({
                    price: pool.price,
                    color: pool.type === 'BSL' ? 'rgba(255,23,68,0.5)' : 'rgba(0,200,83,0.5)',
                    lineWidth: 1,
                    lineStyle: 3,
                    axisLabelVisible: true,
                    title: `${pool.type} $${pool.price.toFixed(0)}`,
                });
            });
        }
    }

    clearOverlays() {
        // Remove all price lines
        ['fvg', 'ob', 'bos'].forEach(key => {
            this.overlays[key].forEach(line => {
                try { this.candleSeries.removePriceLine(line); } catch(e) {}
            });
            this.overlays[key] = [];
        });
        if (this.overlays.ote) {
            this.overlays.ote.forEach(line => {
                try { this.candleSeries.removePriceLine(line); } catch(e) {}
            });
            this.overlays.ote = null;
        }
        this.candleSeries.setMarkers([]);
        this.markers = [];
    }
}
