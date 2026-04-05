/**
 * Backtest Player — Interactive manual walk-forward mode.
 * Reveals candles one-by-one to train the trader's eye.
 */

class BacktestPlayer {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.chart = null;
        this.candleSeries = null;
        this.isPlaying = false;
        this.currentStep = 0;
        this.trades = [];
        this.init();
    }

    async init() {
        if (!window.LightweightCharts) return;
        this.chart = LightweightCharts.createChart(this.container, {
            width: this.container.clientWidth,
            height: 400,
            layout: { background: { color: '#0a0e17' }, textColor: '#8899aa' },
            grid: { vertLines: { color: '#1e2a3a' }, horzLines: { color: '#1e2a3a' } },
        });
        this.candleSeries = this.chart.addCandlestickSeries();
    }

    async startManualSession(tf) {
        this.trades = [];
        this.currentStep = 0;
        this.candleSeries.setData([]);
        document.getElementById('manual-controls').style.display = 'flex';
        this.step(); // Load first bar
    }

    async step() {
        try {
            const resp = await fetch('/api/backtest/step');
            const state = await resp.json();
            if (!state) {
                alert("End of historical data.");
                return;
            }
            this.updateChart(state);
            this.updateInfo(state);
        } catch (e) { console.error(e); }
    }

    updateChart(state) {
        const c = state.candle;
        this.candleSeries.update({
            time: c.datetime,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close
        });
    }

    updateInfo(state) {
        const infoEl = document.getElementById('manual-info');
        if (state.score >= 8) {
            infoEl.innerHTML = `🎯 <b>SETUP DETECTED!</b> Score: ${state.score} | Grade: ${state.grade}<br>
            <button class="action-btn primary" onclick="btPlayer.takeTrade()">Take Trade</button>
            <button class="action-btn secondary" onclick="btPlayer.step()">Skip</button>`;
        } else {
            infoEl.innerHTML = `Price: $${state.candle.close.toFixed(2)} | Scanning...`;
        }
    }

    takeTrade() {
        alert("Trade recorded! (Simulation pending)");
        this.step();
    }
}
