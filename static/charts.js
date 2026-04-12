/**
 * BacktestPlayer - Handles manual bar-by-bar backtest simulation.
 */
class BacktestPlayer {
    constructor(containerId) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);
        this.currentStep = 0;
        this.totalSteps = 0;
        this.isPlaying = false;
        this.timer = null;
        this.speed = 500; // ms per step
    }

    async startManualSession() {
        const tf = document.getElementById('bt-timeframe')?.value || '15min';
        const start = document.getElementById('bt-start-date')?.value;
        const end = document.getElementById('bt-end-date')?.value;

        try {
            const resp = await fetch('/api/backtest/manual/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ timeframe: tf, start_date: start, end_date: end })
            });
            const data = await resp.json();
            if (data.success) {
                this.totalSteps = data.total_bars;
                this.currentStep = 0;
                this.updateProgress();
                this.nextStep(); // Load first bar
            } else {
                alert(data.error || 'Failed to start manual session');
            }
        } catch (e) {
            console.error('Manual start error:', e);
        }
    }

    async nextStep() {
        try {
            const resp = await fetch('/api/backtest/step');
            if (resp.status === 404) {
                this.stopAuto();
                alert('End of historical data reached.');
                return;
            }
            const data = await resp.json();
            this.currentStep++;
            this.updateUI(data);
            this.updateProgress();
        } catch (e) {
            console.error('Step error:', e);
            this.stopAuto();
        }
    }

    updateUI(state) {
        if (!state) return;

        // 1. Update Price Label
        const priceEl = document.getElementById('bt-current-price');
        if (priceEl) priceEl.textContent = `$${state.candle.close.toFixed(2)}`;

        // 2. Update Confluence Matrix
        if (window.analyst && state.confluence) {
            window.analyst.onConfluence({
                factors: state.confluence.reduce((acc, f) => {
                    const key = f.name.toLowerCase().replace(/ /g, '_');
                    acc[key] = { status: f.score > 0 ? '✅' : '❌', detail: f.name, score: f.score };
                    return acc;
                }, {}),
                total: state.score,
                maximum: 12.0
            });
        }

        // 3. Update Checklist
        const list = document.getElementById('bt-checklist');
        if (list && state.ict_checklist) {
            list.innerHTML = state.ict_checklist.map(item => `
                <div class="check-item ${item.checked ? 'pass' : 'fail'}">
                    <i class="fas ${item.checked ? 'fa-check' : 'fa-times'}"></i>
                    <span>${item.label}</span>
                </div>
            `).join('');
        }

        // 4. Update Strategy Banner
        const banner = document.getElementById('bt-action-banner');
        if (banner) {
            banner.textContent = state.grade !== 'None' ? `🚀 ${state.grade} SETUP DETECTED` : '💤 No setup detected';
            banner.className = 'bt-banner ' + (state.grade !== 'None' ? 'active' : '');
        }
        
        // 5. Update Institutional Levels (FVG/OB)
        if (state.levels && window.analyst) {
            window.analyst.onIndicators(state.levels);
        }
    }

    updateProgress() {
        const prog = document.getElementById('bt-progress-bar');
        const text = document.getElementById('bt-progress-text');
        if (prog) prog.style.width = ((this.currentStep / this.totalSteps) * 100) + '%';
        if (text) text.textContent = `Bar ${this.currentStep} / ${this.totalSteps}`;
    }

    play() {
        if (this.isPlaying) return;
        this.isPlaying = true;
        document.getElementById('btn-bt-play').innerHTML = '<i class="fas fa-pause"></i> Pause';
        this.timer = setInterval(() => this.nextStep(), this.speed);
    }

    stopAuto() {
        this.isPlaying = false;
        if (this.timer) clearInterval(this.timer);
        const btn = document.getElementById('btn-bt-play');
        if (btn) btn.innerHTML = '<i class="fas fa-play"></i> Play';
    }

    togglePlay() {
        if (this.isPlaying) this.stopAuto();
        else this.play();
    }
}
