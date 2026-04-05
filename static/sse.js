/**
 * HTML Elements — Cache for easy access
 */
const mainTabs = ['dashboard', 'backtest'];

function switchMainTab(tabId) {
    mainTabs.forEach(id => {
        const el = document.getElementById(id + '-tab');
        if (el) el.style.display = (id === tabId) ? 'block' : 'none';
    });
    
    // Update header buttons
    const btns = document.querySelectorAll('.nav-tabs .chart-tab');
    btns.forEach(btn => {
        btn.classList.toggle('active', btn.textContent.toLowerCase() === tabId);
    });
}

let btPlayer = null;

function startManualBacktest() {
    const tf = document.getElementById('bt-timeframe').value;
    document.getElementById('manual-player-view').style.display = 'block';
    document.getElementById('bt-results').style.display = 'none';
    
    if (!btPlayer) {
        btPlayer = new BacktestPlayer('manual-chart-container');
    }

    fetch('/api/backtest/manual/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ timeframe: tf })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            btPlayer.startManualSession(tf);
        }
    });
}

function runBacktest() {
    const tf = document.getElementById('bt-timeframe').value;
    const btn = document.getElementById('btn-run-bt');
    btn.disabled = true;
    btn.textContent = '⏳ Running...';
    
    fetch('/api/backtest/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ timeframe: tf })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            btn.textContent = '✅ Complete';
            document.getElementById('bt-results').style.display = 'block';
            fetchLatestBacktestResults();
        } else {
            alert(data.error || 'Backtest failed');
            btn.textContent = '▶ Run Backtest';
            btn.disabled = false;
        }
    })
    .catch(e => {
        console.error(e);
        btn.textContent = '▶ Run Backtest';
        btn.disabled = false;
    });
}

async function fetchLatestBacktestResults() {
    try {
        const resp = await fetch('/api/backtest/latest');
        const trades = await resp.json();
        const tbody = document.querySelector('#bt-trades-table tbody');
        tbody.innerHTML = '';
        
        trades.forEach(t => {
            const row = document.createElement('tr');
            row.style.borderBottom = '1px solid var(--border)';
            row.innerHTML = `
                <td style="padding:10px;">${t.timestamp}</td>
                <td style="padding:10px;">$${t.price.toFixed(2)}</td>
                <td style="padding:10px;">${t.score}</td>
                <td style="padding:10px; color:${t.pnl >= 0 ? 'var(--green)' : 'var(--red)'}">${t.result.toUpperCase()} ($${t.pnl.toFixed(2)})</td>
            `;
            tbody.appendChild(row);
        });
    } catch (e) {
        console.error(e);
    }
}

/**
 * SSE Listener — Real-time dashboard updates via Server-Sent Events.
 */

class GoldAnalystSSE {
    constructor() {
        this.source = null;
        this.reconnectDelay = 1000;
        this.maxReconnectDelay = 30000;
        this.state = {};
        this.charts = new GoldCharts('chart-container');
        this.connect();
        this.fetchInitialStatus();
        this.startClock();
    }

    connect() {
        this.source = new EventSource('/api/stream');

        this.source.onopen = () => {
            console.log('SSE connected');
            this.reconnectDelay = 1000;
            this.updateConnectionStatus(true);
        };

        this.source.onerror = () => {
            console.warn('SSE error — reconnecting...');
            this.updateConnectionStatus(false);
            this.source.close();
            setTimeout(() => this.connect(), this.reconnectDelay);
            this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
        };

        // Event handlers
        this.source.addEventListener('tick', (e) => this.handleTick(JSON.parse(e.data)));
        this.source.addEventListener('candle_close', (e) => this.handleCandleUpdate(JSON.parse(e.data)));
        this.source.addEventListener('health', (e) => this.handleHealth(JSON.parse(e.data)));
        this.source.addEventListener('feed_status', (e) => this.handleFeedStatus(JSON.parse(e.data)));
        this.source.addEventListener('confluence_update', (e) => this.handleConfluence(JSON.parse(e.data)));
        this.source.addEventListener('indicator_update', (e) => this.handleIndicators(JSON.parse(e.data)));
        this.source.addEventListener('alert', (e) => this.handleAlert(JSON.parse(e.data)));
        this.source.addEventListener('state', (e) => this.handleFullState(JSON.parse(e.data)));
        this.source.addEventListener('ping', () => {});
    }

    async fetchInitialStatus() {
        try {
            const resp = await fetch('/api/status');
            const data = await resp.json();
            this.updateDashboard(data);
        } catch (e) {
            console.warn('Failed to fetch initial status:', e);
        }
    }

    startClock() {
        setInterval(() => {
            const now = new Date();
            const ist = new Date(now.getTime() + (5.5 * 60 * 60 * 1000) - (now.getTimezoneOffset() * 60 * 1000));
            const el = document.getElementById('clock');
            if (el) el.textContent = ist.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) + ' IST';
        }, 1000);
    }

    // ─── Event Handlers ────────────────────────────────────

    handleTick(data) {
        const priceEl = document.getElementById('live-price');
        if (priceEl && data.price) {
            const oldPrice = parseFloat(priceEl.textContent.replace('$', '').replace(',', ''));
            // Update chart
            this.charts.updateCandle({
                timeframe: this.charts.activeTimeframe,
                timestamp: Math.floor(Date.now() / 1000),
                price: data.price,
                open: data.price, // simplistic for tick
                high: data.price,
                low: data.price,
                close: data.price
            });

            // Flash animation
            priceEl.classList.remove('flash-up', 'flash-down');
            if (data.price > oldPrice) priceEl.classList.add('flash-up');
            else if (data.price < oldPrice) priceEl.classList.add('flash-down');
            setTimeout(() => priceEl.classList.remove('flash-up', 'flash-down'), 300);
        }
    }

    handleCandleUpdate(data) {
        console.log(`Candle update/close: ${data.timeframe}`, data.candle);
        if (this.charts) {
            this.charts.handleCandleUpdate(data);
        }
    }

    handleHealth(data) {
        // Update feed status indicators
        const primaryDot = document.getElementById('feed-primary-dot');
        const fallbackDot = document.getElementById('feed-fallback-dot');
        const sourceEl = document.getElementById('feed-source');

        if (primaryDot) {
            primaryDot.className = 'feed-dot ' + (data.primary?.connected ? 'connected' : 'disconnected');
        }
        if (fallbackDot) {
            fallbackDot.className = 'feed-dot ' + (data.fallback?.connected ? (data.fallback?.active ? 'connected' : 'standby') : 'disconnected');
        }
        if (sourceEl) {
            sourceEl.textContent = data.current_source || 'unknown';
        }
    }

    handleFeedStatus(data) {
        if (data.event === 'failover') {
            this.showAlert('warning', `⚠️ Feed switched to ${data.to}. Primary recovering.`);
        } else if (data.event === 'restored') {
            this.showAlert('info', '✅ Primary feed restored.');
        }
    }

    handleConfluence(data) {
        const scoreEl = document.getElementById('confluence-score');
        const fillEl = document.getElementById('confluence-fill');
        if (scoreEl && data.total !== undefined) {
            scoreEl.textContent = data.total;
            const pct = (data.total / (data.maximum || 12)) * 100;
            if (fillEl) fillEl.style.width = pct + '%';
        }
    }

    handleIndicators(data) {
        // Update indicator values
        const atrEl = document.getElementById('atr-value');
        if (atrEl && data.atr_h1) {
            atrEl.textContent = '$' + data.atr_h1.toFixed(2);
        }
    }

    handleAlert(data) {
        this.showAlert(data.type === 'feed_failover' ? 'warning' : 'info', data.message);
    }

    handleFullState(data) {
        // Full state update — update everything
        Object.assign(this.state, data);
    }

    // ─── Dashboard Update ──────────────────────────────────

    updateDashboard(data) {
        // Session / Status
        const statusBadge = document.getElementById('status-badge');
        if (statusBadge && data.session) {
            const light = data.session.status_light || 'RED';
            statusBadge.className = 'status-badge ' + light.toLowerCase();
            statusBadge.querySelector('.status-dot').className = 'status-dot ' + light.toLowerCase();
            statusBadge.querySelector('.status-text').textContent = data.session.killzone_name || data.session.session_label || 'No Killzone';
        }

        // Killzone timer
        const kzTimer = document.getElementById('kz-timer');
        if (kzTimer && data.session) {
            kzTimer.textContent = data.session.killzone_active
                ? `${data.session.killzone_remaining_min} min remaining`
                : data.session.session_label;
        }

        // Price
        const priceEl = document.getElementById('live-price');
        if (priceEl && data.price) {
            priceEl.textContent = '$' + data.price.toFixed(2);
        }

        // Account
        if (data.account) {
            this.updateElement('weekly-pnl', '$' + (data.account.weekly_pnl || 0).toFixed(0));
            this.updateElement('daily-pnl', '$' + (data.account.daily_pnl || 0).toFixed(0));
            this.updateElement('trades-today', data.account.trades_today || 0);

            // Weekly progress bar
            const progressFill = document.getElementById('weekly-progress');
            if (progressFill) {
                const pct = Math.min(100, ((data.account.weekly_pnl || 0) / 300) * 100);
                progressFill.style.width = pct + '%';
            }
        }

        // Trading blocked
        if (data.trading_blocked) {
            const reportBtn = document.getElementById('btn-generate-report');
            if (reportBtn) {
                reportBtn.disabled = data.trading_blocked.blocked;
            }
        }

        // Macro
        if (data.macro_bias) {
            this.updateElement('macro-bias', data.macro_bias);
        }
    }

    // ─── Utilities ─────────────────────────────────────────

    updateElement(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    showAlert(type, message) {
        const banner = document.getElementById('alert-banner');
        if (banner) {
            banner.className = 'alert-banner ' + (type === 'warning' ? 'warning' : 'danger');
            banner.querySelector('.alert-text').textContent = message;
            setTimeout(() => { banner.className = 'alert-banner'; }, 10000);
        }
    }

    updateConnectionStatus(connected) {
        const el = document.getElementById('sse-status');
        if (el) {
            el.textContent = connected ? '● Live' : '○ Reconnecting...';
            el.style.color = connected ? 'var(--green)' : 'var(--yellow)';
        }
    }
}

// ─── Psychology Modal ──────────────────────────────────────

function openPsychologyModal() {
    document.getElementById('psych-modal').classList.add('active');
}

function closePsychologyModal() {
    document.getElementById('psych-modal').classList.remove('active');
}

function updateSliderValue(val) {
    document.getElementById('feeling-value').textContent = val;
}

async function submitPsychology() {
    const feeling = parseInt(document.getElementById('feeling-slider').value);
    const sleptWell = document.getElementById('toggle-sleep').classList.contains('active');
    const financialStress = document.getElementById('toggle-stress').classList.contains('active');
    const lastTrade = document.querySelector('input[name="last-trade"]:checked')?.value || 'none';
    const reason = document.querySelector('input[name="reason"]:checked')?.value || 'routine_check';

    try {
        const resp = await fetch('/api/psychology', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ feeling, slept_well: sleptWell, financial_stress: financialStress, last_trade: lastTrade, reason }),
        });
        const result = await resp.json();

        closePsychologyModal();

        if (result.blocked) {
            showBlockedMessage(result.block_reason);
        } else {
            document.getElementById('psych-status').textContent = result.assessment;
            document.getElementById('psych-status').className = 'info-item value ok';
            document.getElementById('btn-generate-report').onclick = openScreenshotModal;
            document.getElementById('btn-generate-report').disabled = false;
            
            // Auto-switch to dashboard tab if we were checking psych
            switchMainTab('dashboard');

            if (result.warning) {
                showWarning(result.warning);
            }
        }
    } catch (e) {
        console.error('Psychology submit failed:', e);
    }
}

function showBlockedMessage(reason) {
    const banner = document.getElementById('alert-banner');
    if (banner) {
        banner.className = 'alert-banner danger';
        banner.querySelector('.alert-text').textContent = '🚫 ' + reason;
    }
}

function showWarning(msg) {
    const banner = document.getElementById('alert-banner');
    if (banner) {
        banner.className = 'alert-banner warning';
        banner.querySelector('.alert-text').textContent = msg;
    }
}

function toggleButton(id) {
    document.getElementById(id).classList.toggle('active');
}

// ─── Screenshot Modal ──────────────────────────────────────

function openScreenshotModal() {
    document.getElementById('screenshot-modal').classList.add('active');
}

function closeScreenshotModal() {
    document.getElementById('screenshot-modal').classList.remove('active');
}

function confirmScreenshots() {
    // Check if all checkboxes are checked
    const checks = document.querySelectorAll('.check-item');
    const allChecked = Array.from(checks).every(c => c.checked);
    
    if (!allChecked) {
        alert('Please complete all checklist items before continuing.');
        return;
    }

    closeScreenshotModal();
    generateReport();
}

// ─── Report Generation ─────────────────────────────────────

async function generateReport() {
    const btn = document.getElementById('btn-generate-report');
    btn.disabled = true;
    btn.textContent = '⏳ Generating...';

    try {
        const resp = await fetch('/api/report', { method: 'POST' });
        const result = await resp.json();

        if (result.success) {
            btn.textContent = '✅ Report Ready — Download';
            btn.onclick = () => window.open(result.download_url, '_blank');
            btn.disabled = false;
        } else {
            btn.textContent = '❌ Failed — Try Again';
            btn.disabled = false;
        }
    } catch (e) {
        console.error('Report generation failed:', e);
        btn.textContent = '❌ Error — Try Again';
        btn.disabled = false;
    }
}

// ─── Initialize ─────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    window.analyst = new GoldAnalystSSE();
});
