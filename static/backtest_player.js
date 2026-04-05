/* ═══════════════════════════════════════════════════════
   AURUM — BacktestPlayer (klinecharts v8)
   Manual step-by-step candle replay engine
   ═══════════════════════════════════════════════════════ */

'use strict';

class BacktestPlayer {
    constructor(containerId) {
        this.containerId    = containerId;
        this.chart          = null;
        this.isAutoPlaying  = false;
        this.autoTimer      = null;
        this.playSpeed      = 1000;      // ms between steps
        this.tradeLog       = [];
        this.lastSignalTs   = 0;
        this.activeInds     = new Set();

        this._init();
    }

    // ─── Initialization ────────────────────────────────

    _init() {
        if (!window.klinecharts) {
            console.error('[BacktestPlayer] klinecharts not loaded.');
            return;
        }

        const container = document.getElementById(this.containerId);
        if (!container) {
            console.error('[BacktestPlayer] Container not found:', this.containerId);
            return;
        }

        this.chart = klinecharts.init(container, {
            styles: {
                grid: {
                    horizontal: { color: 'rgba(255,255,255,0.03)', style: 'dashed', size: 1 },
                    vertical:   { color: 'rgba(255,255,255,0.03)', style: 'dashed', size: 1 },
                },
                candle: {
                    type: 'candle_solid',
                    bar: {
                        upColor:     '#00e676',
                        downColor:   '#ff3d57',
                        noChangeColor: '#607d8b',
                        upBorderColor:   '#00e676',
                        downBorderColor: '#ff3d57',
                        upWickColor:     '#00e676',
                        downWickColor:   '#ff3d57',
                    }
                },
                yAxis: { textColor: '#546e7a' },
                xAxis: { textColor: '#546e7a' },
                crosshair: { horizontal: { line: { color: 'rgba(245,166,35,0.3)' } }, vertical: { line: { color: 'rgba(245,166,35,0.3)' } } },
            }
        });

        if (this.chart) {
            this._tryAddIndicator('MA');
        }
    }

    _tryAddIndicator(name) {
        if (!this.chart) return;
        try {
            this.chart.createTechnicalIndicator(name, true, { id: 'candle_pane' });
        } catch {
            try { this.chart.createIndicator(name, true, { id: 'candle_pane' }); } catch {}
        }
        this.activeInds.add(name);
    }

    // ─── Manual Session ─────────────────────────────────

    async startManualSession() {
        if (!this.chart) this._init();
        if (!this.chart) { alert('Chart failed to initialize. Refresh and try again.'); return; }

        this.stopAuto();
        try { this.chart.applyNewData([]); } catch {}
        this._clearOverlays();
        this.tradeLog     = [];
        this.lastSignalTs = 0;
        this._renderLog();

        const tf        = document.getElementById('bt-timeframe')?.value   || '15min';
        const startDate = document.getElementById('bt-start-date')?.value  || '';
        const endDate   = document.getElementById('bt-end-date')?.value    || '';

        try {
            const resp = await fetch('/api/backtest/manual/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ timeframe: tf, start_date: startDate, end_date: endDate })
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                alert(err.error || `Server error: ${resp.status}`);
                return;
            }

            const res = await resp.json();
            if (!res.success) { alert(res.error || 'Failed to start session.'); return; }

            // Resize chart now that the container is visible
            try { this.chart.resize(); } catch {}

            this._updateProgress(0, res.total_bars);
            this._setInfo('Session ready (' + res.total_bars + ' bars). Press ▶ to begin.', false);
            await this.step();

        } catch (e) {
            console.error('[BacktestPlayer] startManualSession error:', e);
            alert('Could not connect to server: ' + e.message);
        }
    }

    // ─── Step ───────────────────────────────────────────

    async step() {
        try {
            const resp = await fetch('/api/backtest/step');

            if (resp.status === 404) {
                this.stopAuto();
                this._setInfo('✅ End of data — simulation complete.', false);
                return null;
            }
            if (!resp.ok) {
                console.warn('[BacktestPlayer] step() got status', resp.status);
                this.stopAuto();
                return null;
            }

            const state = await resp.json();
            if (!state || state.error) {
                this.stopAuto();
                return null;
            }

            this._updateChart(state);
            this._updateInfo(state);
            this._updateDetails(state);
            this._updateProgress(state.progress?.current ?? 0, state.progress?.total ?? 1);

            try { this._updateOverlays(state); } catch {}

            return state;

        } catch (e) {
            console.error('[BacktestPlayer] step() error:', e.message);
            // Don't stopAuto on transient network errors
            return null;
        }
    }

    // ─── Chart Update ────────────────────────────────────

    _updateChart(state) {
        const c = state.candle;
        if (!c || !this.chart) return;

        // klinecharts v8 needs milliseconds
        const ts = Number(c.datetime || c.timestamp);
        this.chart.updateData({
            timestamp: ts < 1e10 ? ts * 1000 : ts,   // auto-detect seconds vs ms
            open:      parseFloat(c.open),
            high:      parseFloat(c.high),
            low:       parseFloat(c.low),
            close:     parseFloat(c.close),
            volume:    parseFloat(c.volume || 0)
        });
    }

    // ─── Overlays ────────────────────────────────────────

    _clearOverlays() {
        for (let i = 0; i < 30; i++) {
            try { this.chart.removeShape(`fvg_${i}`); } catch {}
            try { this.chart.removeShape(`ob_${i}`);  } catch {}
        }
    }

    _updateOverlays(state) {
        this._clearOverlays();
        const inds = state.indicators;
        if (!inds) return;

        (inds.fvg || []).slice(0, 15).forEach((f, i) => {
            const ts = Number(f.start_time);
            const te = Number(f.end_time);
            this.chart.createShape?.({
                name: 'rect',
                id: `fvg_${i}`,
                points: [
                    { timestamp: ts < 1e10 ? ts * 1000 : ts, value: parseFloat(f.high) },
                    { timestamp: te < 1e10 ? te * 1000 : te, value: parseFloat(f.low)  }
                ],
                styles: { polygon: { color: 'rgba(41,182,246,0.12)' }, line: { show: false } },
                lock: true
            });
        });

        (inds.ob || []).slice(0, 15).forEach((o, i) => {
            const ts = Number(o.start_time);
            const te = Number(o.end_time);
            const col = o.direction === 'bullish' ? 'rgba(0,230,118,0.12)' : 'rgba(255,61,87,0.12)';
            this.chart.createShape?.({
                name: 'rect',
                id: `ob_${i}`,
                points: [
                    { timestamp: ts < 1e10 ? ts * 1000 : ts, value: parseFloat(o.high) },
                    { timestamp: te < 1e10 ? te * 1000 : te, value: parseFloat(o.low)  }
                ],
                styles: { polygon: { color: col }, line: { show: false } },
                lock: true
            });
        });
    }

    // ─── Info / Details ──────────────────────────────────

    _setInfo(text, isSignal = false) {
        const el = document.getElementById('manual-info');
        if (!el) return;
        el.textContent  = text;
        el.className    = 'player-info' + (isSignal ? ' signal' : '');
    }

    _updateInfo(state) {
        if (!state.candle) return;

        const price = parseFloat(state.candle.close).toFixed(2);
        const ts    = Number(state.candle.datetime || state.candle.timestamp);
        const dt    = new Date(ts < 1e10 ? ts * 1000 : ts).toLocaleString('en-IN', {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false
        });

        const score = state.score ?? 0;
        const isSignal = score >= 5;

        if (isSignal) {
            this._setInfo(`🎯 SETUP: ${state.grade} | Score ${score.toFixed(1)}/12 | ${state.direction || '?'} | $${price} — ${dt}`, true);

            // Log deduped signals (min 1h apart)
            if (ts - this.lastSignalTs >= 3600) {
                this.lastSignalTs = ts;
                this.tradeLog.unshift({ time: dt, price, direction: state.direction, score: score.toFixed(1), grade: state.grade });
                this._renderLog();
            }
        } else {
            this._setInfo(`Scanning... $${price} — ${dt}`, false);
        }
    }

    _updateDetails(state) {
        // ICT Steps
        if (state.ict_checklist) {
            const el = document.getElementById('manual-ict-steps');
            if (el) {
                el.innerHTML = state.ict_checklist.map(s => `
                    <div style="display:flex; justify-content:space-between; align-items:center; padding:7px 0; border-bottom:1px solid rgba(255,255,255,0.04); font-size:11px;">
                        <span style="color:${s.checked ? 'var(--c-text)' : 'var(--c-text-3)'};">${s.label}</span>
                        <span style="color:${s.checked ? 'var(--c-green)' : 'var(--c-text-3)'};">${s.checked ? '✅' : '○'}</span>
                    </div>`
                ).join('');
            }
        }
    }

    _renderLog() {
        const el    = document.getElementById('manual-trade-log');
        const badge = document.getElementById('signal-count-badge');
        if (badge) badge.textContent = this.tradeLog.length;
        if (!el) return;

        if (!this.tradeLog.length) {
            el.innerHTML = '<div style="color:var(--c-text-3); padding:12px 0; font-size:11px;">No signals detected yet...</div>';
            return;
        }

        el.innerHTML = this.tradeLog.map(t => `
            <div class="signal-entry">
                <div>
                    <span style="font-weight:700; color:${t.direction === 'bullish' ? 'var(--c-green)' : 'var(--c-red)'};">
                        ${t.direction === 'bullish' ? '↑' : '↓'} $${t.price}
                    </span>
                </div>
                <span class="chip chip-gold" style="font-size:9px;">${t.score} · ${t.grade}</span>
                <span style="color:var(--c-text-3); font-size:10px;">${t.time}</span>
            </div>`
        ).join('');
    }

    _updateProgress(current, total) {
        // We don't have a progress bar in the new HTML, so just log it
        // Could add one in the player-header if needed
    }

    // ─── Auto Play ───────────────────────────────────────

    toggleAuto() {
        if (this.isAutoPlaying) this.stopAuto();
        else this.startAuto();
    }

    startAuto() {
        this.isAutoPlaying = true;
        const btn = document.getElementById('btn-bt-play');
        if (btn) btn.textContent = '⏸';
        this._autoLoop();
    }

    stopAuto() {
        this.isAutoPlaying = false;
        clearTimeout(this.autoTimer);
        const btn = document.getElementById('btn-bt-play');
        if (btn) btn.textContent = '▶';
    }

    async _autoLoop() {
        if (!this.isAutoPlaying) return;
        const state = await this.step();
        if (state === null) {
            // End of data or unrecoverable error
            this.stopAuto();
            return;
        }
        if (this.isAutoPlaying) {
            this.autoTimer = setTimeout(() => this._autoLoop(), this.playSpeed);
        }
    }

    updateSpeed(val) {
        this.playSpeed = 2200 - parseInt(val);
    }

    // ─── Indicator Toggle ────────────────────────────────

    toggleIndicator(name) {
        if (this.activeInds.has(name)) {
            try { this.chart.removeTechnicalIndicator('candle_pane', name); } catch {
                try { this.chart.removeIndicator('candle_pane', name); } catch {}
            }
            this.activeInds.delete(name);
        } else {
            this._tryAddIndicator(name);
        }
    }

    stop() { this.stopAuto(); }
}
