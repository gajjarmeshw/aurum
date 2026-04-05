/* ═══════════════════════════════════════════════════════
   AURUM — Global Tab + UI Controller + SSE Client
   ═══════════════════════════════════════════════════════ */

'use strict';

// ── Tab Management ─────────────────────────────────────
const TABS = ['terminal', 'backtest', 'alerts'];

function switchTab(id) {
    TABS.forEach(t => {
        const view = document.getElementById('view-' + t);
        const btn  = document.getElementById('tab-' + t);
        if (view) view.style.display = t === id ? 'block' : 'none';
        if (btn)  btn.classList.toggle('active', t === id);
    });
}

// ── Modal Manager ───────────────────────────────────────
function openModal(id) {
    const el = document.getElementById(id);
    if (el) { requestAnimationFrame(() => el.classList.add('open')); }
    else { console.error('Modal not found:', id); }
}
function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('open');
}

// Close on backdrop click
document.addEventListener('click', e => {
    if (e.target.classList.contains('modal-backdrop')) {
        e.target.classList.remove('open');
    }
});

// ── Alert Banner ────────────────────────────────────────
function showBanner(msg, type = 'red') {
    const b   = document.getElementById('alert-banner');
    const txt = document.getElementById('alert-text');
    if (!b || !txt) return;
    txt.textContent   = msg;
    b.style.background = type === 'green' ? 'var(--c-green)' : type === 'gold' ? 'var(--c-gold)' : 'var(--c-red)';
    b.style.color      = type === 'gold' ? '#000' : '#fff';
    b.classList.add('show');
    setTimeout(() => b.classList.remove('show'), 6000);
}

// ── Manual Backtest bootstrap ───────────────────────────
let btPlayer = null;

function initManualPlayer() {
    switchTab('backtest');

    if (!btPlayer) {
        btPlayer = new BacktestPlayer('manual-chart-container');
        window.btPlayer = btPlayer;
    }

    // Show player area, hide auto results
    document.getElementById('manual-player-view').style.display = 'block';
    document.getElementById('bt-results-area').style.display    = 'none';

    btPlayer.startManualSession();
}

// ── Auto Backtest ───────────────────────────────────────
function runAutoBacktest() {
    const btn       = document.getElementById('btn-run-bt');
    const tf        = document.getElementById('bt-timeframe')?.value;
    const startDate = document.getElementById('bt-start-date')?.value;
    const endDate   = document.getElementById('bt-end-date')?.value;

    if (!tf) { showBanner('Select a timeframe first.'); return; }

    // Stop manual player if running
    if (window.btPlayer) window.btPlayer.stopAuto();
    document.getElementById('manual-player-view').style.display = 'none';
    document.getElementById('bt-results-area').style.display    = 'none';

    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Running...';

    fetch('/api/backtest/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ timeframe: tf, start_date: startDate, end_date: endDate })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            btn.innerHTML = '<i class="fas fa-check"></i> Done';
            populateAutoResults(data);
            document.getElementById('bt-results-area').style.display = 'block';
            setTimeout(() => { btn.innerHTML = '<i class="fas fa-rocket"></i> Auto'; btn.disabled = false; }, 4000);
        } else {
            showBanner(data.error || 'Backtest failed. Check server logs.');
            btn.innerHTML = '<i class="fas fa-rocket"></i> Auto';
            btn.disabled = false;
        }
    })
    .catch(err => {
        console.error('Auto backtest error:', err);
        showBanner('Network error running backtest.');
        btn.innerHTML = '<i class="fas fa-rocket"></i> Auto';
        btn.disabled = false;
    });
}

let _allBtResults = [];

function populateAutoResults(data) {
    const summary = data.summary || {};
    _setEl('bt-stat-total',   data.setups_found ?? '—');
    _setEl('bt-stat-winrate', summary.win_rate ?? '—');
    _setEl('bt-stat-ratio',   `${summary.wins ?? 0}W / ${summary.losses ?? 0}L`);
    const pnlEl = document.getElementById('bt-stat-pnl');
    if (pnlEl) {
        pnlEl.textContent = summary.total_pnl ?? '$0';
        const pnlNum = parseFloat((summary.total_pnl || '0').replace('$', ''));
        pnlEl.style.color = pnlNum >= 0 ? 'var(--c-green)' : 'var(--c-red)';
    }

    // Fetch full results
    fetchLatestBtResults();
}

function fetchLatestBtResults() {
    fetch('/api/backtest/latest')
        .then(r => r.json())
        .then(rows => { _allBtResults = rows; renderBtTable(rows); })
        .catch(console.warn);
}

function renderBtTable(rows) {
    const tbody = document.getElementById('bt-tbody');
    if (!tbody) return;
    if (!rows.length) { tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:var(--c-text-3); padding:24px;">No results found for this date range.</td></tr>'; return; }

    tbody.innerHTML = rows.map(r => {
        const win = r.result === 'win';
        const dt = r.timestamp ? new Date(Number(r.timestamp) * 1000).toLocaleString('en-IN', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' }) : '—';
        return `<tr>
            <td>${dt}</td>
            <td>$${parseFloat(r.price || 0).toFixed(2)}</td>
            <td style="color:${r.direction === 'bullish' ? 'var(--c-green)' : 'var(--c-red)'};">${r.direction === 'bullish' ? '↑ LONG' : '↓ SHORT'}</td>
            <td>${parseFloat(r.score || 0).toFixed(1)}</td>
            <td><span class="chip ${r.grade === 'A+' ? 'chip-gold' : r.grade === 'A' ? 'chip-green' : 'chip-dim'}">${r.grade || '—'}</span></td>
            <td><span class="chip ${win ? 'chip-green' : 'chip-red'}">${win ? 'WIN' : 'LOSS'}</span></td>
            <td style="color:${(r.pnl || 0) >= 0 ? 'var(--c-green)' : 'var(--c-red)'};">$${parseFloat(r.pnl || 0).toFixed(2)}</td>
        </tr>`;
    }).join('');
}

function filterResults() {
    const grade  = document.getElementById('filter-grade')?.value  || 'all';
    const result = document.getElementById('filter-result')?.value || 'all';
    const filtered = _allBtResults.filter(r => {
        const gMatch = grade  === 'all' || r.grade  === grade;
        const rMatch = result === 'all' || r.result === result;
        return gMatch && rMatch;
    });
    renderBtTable(filtered);
}

// ── Data Range loader ───────────────────────────────────
function loadDataRange() {
    fetch('/api/backtest/data-range')
        .then(r => r.json())
        .then(d => {
            _setEl('bt-data-min', d.min_date || 'N/A');
            _setEl('bt-data-max', d.max_date || 'N/A');
        })
        .catch(() => {
            _setEl('bt-data-min', 'N/A');
            _setEl('bt-data-max', 'N/A');
        });
}

// ── Psychology Modal ─────────────────────────────────────
function handleGenerateReport() {
    openModal('screenshot-modal');
}

async function submitPsychology() {
    const feeling       = parseInt(document.getElementById('feeling-slider').value);
    const sleptWell     = document.getElementById('toggle-sleep').classList.contains('on');
    const financialStress = document.getElementById('toggle-stress').classList.contains('on');
    const lastTrade     = document.querySelector('input[name="last-trade"]:checked')?.value || 'none';

    try {
        const resp   = await fetch('/api/psychology', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ feeling, slept_well: sleptWell, financial_stress: financialStress, last_trade: lastTrade, reason: 'session_check' }),
        });
        const result = await resp.json();
        closeModal('psych-modal');

        if (result.blocked) {
            showBanner('🚫 TRADING BLOCKED: ' + result.block_reason);
        } else {
            _setEl('psych-badge', 'READY');
            const badge = document.getElementById('psych-badge');
            if (badge) { badge.className = 'chip chip-green'; }
            const reportBtn = document.getElementById('btn-generate-report');
            if (reportBtn) reportBtn.disabled = false;
            showBanner('✅ Psychology check passed — report unlocked', 'green');
        }
    } catch (e) {
        console.error('Psychology submit failed:', e);
        showBanner('Failed to submit. Check server.');
    }
}

function confirmAndReport() {
    const checks     = document.querySelectorAll('.check-item');
    const allChecked = Array.from(checks).every(c => c.checked);
    if (!allChecked) { showBanner('Please check all verification items first.', 'gold'); return; }
    closeModal('screenshot-modal');
    generateReport();
}

async function generateReport() {
    const btn = document.getElementById('btn-generate-report');
    if (!btn) return;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating...';

    try {
        const resp   = await fetch('/api/report', { method: 'POST' });
        const result = await resp.json();
        if (result.success) {
            btn.innerHTML = '<i class="fas fa-download"></i> Download Report';
            btn.onclick   = () => {
                const link = document.createElement('a');
                link.href = result.download_url;
                link.download = result.filename;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
            };
            btn.disabled  = false;
        } else {
            btn.innerHTML = '<i class="fas fa-file-contract"></i> Retry Report';
            btn.disabled  = false;
        }
    } catch (e) {
        btn.innerHTML = '<i class="fas fa-file-contract"></i> Retry Report';
        btn.disabled  = false;
    }
}

// ── Telegram Test Alerts ────────────────────────────────
async function sendTestAlert(type) {
    const btnMap = {
        setup:      'btn-test-setup',
        failover:   'btn-test-failover',
        edge_decay: 'btn-test-decay',
        handoff:    'btn-test-handoff'
    };
    const btn = document.getElementById(btnMap[type]);
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Sending...'; }

    try {
        const resp   = await fetch('/api/alerts/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type })
        });
        const result = await resp.json();
        if (result.success) {
            showBanner('✅ Telegram alert sent!', 'green');
            addAlertHistory(type, true);
        } else {
            showBanner('❌ Failed: ' + (result.error || 'Check TELEGRAM_BOT_TOKEN in .env'));
            addAlertHistory(type, false);
        }
    } catch (e) {
        showBanner('❌ Network error. Is server running?');
        addAlertHistory(type, false);
    } finally {
        if (btn) {
            setTimeout(() => {
                btn.disabled = false;
                btn.innerHTML = btn.innerHTML.replace('<i class="fas fa-spinner fa-spin"></i> Sending...', '');
            }, 3000);
        }
    }
}

async function refreshBacktestData() {
    const btn = document.getElementById('btn-refresh-data');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Refreshing...';
    }

    try {
        const resp = await fetch('/api/backtest/refresh', { method: 'POST' });
        const result = await resp.json();
        if (result.success) {
            showBanner('✅ Historical data refreshed successfully!', 'green');
            if (typeof loadDataRange === 'function') loadDataRange(); // Refresh the date range display
        } else {
            showBanner('❌ Refresh failed: ' + (result.error || 'Server error'));
        }
    } catch (e) {
        showBanner('❌ Network error during data refresh.');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-sync-alt"></i> Refresh Data';
        }
    }
}

function addAlertHistory(type, success) {
    const hist = document.getElementById('alert-history');
    if (!hist) return;
    const empty = hist.querySelector('div[style*="text-align"]');
    if (empty) empty.remove();

    const now = new Date().toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: true, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const labels = { setup:'Setup Alert', failover:'Feed Failover', edge_decay:'Edge Decay', handoff:'Handoff Report' };
    const entry = document.createElement('div');
    entry.className = 'signal-entry';
    entry.innerHTML = `
        <span style="color:var(--c-text-2);">${labels[type] || type}</span>
        <span class="chip ${success ? 'chip-green' : 'chip-red'}">${success ? '✓ SENT' : '✗ FAILED'}</span>
        <span style="color:var(--c-text-3); font-size:10px;">${now} IST</span>
    `;
    hist.insertBefore(entry, hist.firstChild);
}

// ── Utilities ───────────────────────────────────────────
function _setEl(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}

// ═══════════════════════════════════════════════════════
//  Live SSE Client
// ═══════════════════════════════════════════════════════
class GoldAnalystSSE {
    constructor() {
        // ── Instantiate chart immediately ──────────────
        this.charts = null;
        this.initCharts();

        this.state  = {};
        this.connect();
        this.startClock();
        loadDataRange();

        // Check Telegram status
        fetch('/api/alerts/health')
            .then(r => r.json())
            .then(d => {
                const bar  = document.getElementById('tg-status-bar');
                const text = document.getElementById('tg-status-text');
                if (bar)  bar.className  = 'tg-card ' + (d.telegram ? 'ok' : 'err');
                if (text) text.textContent = d.telegram
                    ? '✅ Telegram connected — alerts fire automatically on live market'
                    : '❌ Telegram not configured — add BOT_TOKEN & CHAT_ID to .env';
            })
            .catch(() => {});
    }

    initCharts() {
        if (typeof GoldCharts !== 'undefined') {
            try {
                this.charts = new GoldCharts('chart-container');
                console.log('[SSE] GoldCharts instantiated.');
            } catch (e) {
                console.error('[SSE] GoldCharts init failed:', e);
            }
        } else {
            console.warn('[SSE] GoldCharts not defined. Retrying in 500ms...');
            setTimeout(() => this.initCharts(), 500);
        }
    }

    connect() {
        this.es = new EventSource('/api/stream');

        this.es.addEventListener('tick',        e => this.onTick(JSON.parse(e.data)));
        this.es.addEventListener('candle',      e => this.onCandle(JSON.parse(e.data)));
        this.es.addEventListener('ict_update',  e => this.onICT(JSON.parse(e.data)));
        this.es.addEventListener('confluence',  e => this.onConfluence(JSON.parse(e.data)));
        this.es.addEventListener('health',      e => this.onHealth(JSON.parse(e.data)));
        this.es.addEventListener('full_state',  e => this.onFullState(JSON.parse(e.data)));
        this.es.addEventListener('indicators',  e => this.onIndicators(JSON.parse(e.data)));

        this.es.onopen  = () => this.setStatus(true);
        this.es.onerror = () => {
            this.setStatus(false);
            setTimeout(() => this.connect(), 5000);
        };
    }

    setStatus(live) {
        const badge = document.getElementById('terminal-badge');
        const txt   = document.getElementById('feed-status-text');
        if (badge) badge.className = 'terminal-badge ' + (live ? 'live' : 'offline');
        if (txt)   txt.textContent = live ? 'LIVE' : 'RECONNECTING';
    }

    startClock() {
        const update = () => {
            const el = document.getElementById('clock');
            if (el) {
                el.textContent = new Date().toLocaleTimeString('en-US', {
                    timeZone: 'Asia/Kolkata',
                    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true
                }) + ' IST';
            }
        };
        update();
        setInterval(update, 1000);
    }

    onTick(data) {
        if (!data.price) return;
        const el = document.getElementById('live-price');
        if (!el) return;
        const prev = parseFloat(el.textContent.replace(/[$,]/g, '')) || 0;
        el.textContent = '$' + data.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        el.className   = 'live-price ' + (data.price > prev ? 'up' : data.price < prev ? 'down' : '');
        setTimeout(() => { if (el) el.className = 'live-price'; }, 600);

        if (this.charts) {
            this.charts.updateCandle({ timeframe: this.charts.activeTimeframe, timestamp: Math.floor(Date.now() / 1000), close: data.price, open: data.price, high: data.price, low: data.price });
        }
    }

    onCandle(data) {
        if (this.charts) this.charts.handleCandleUpdate(data);
    }

    onICT(data) {
        // Update checklist
        const stepsEl = document.getElementById('ict-steps');
        if (stepsEl && data.checklist) {
            const labels = ['Asian Range', 'Liquidity Sweep', 'H1 FVG Return', 'M15 BOS', 'M5 OB Zone', 'Killzone Active'];
            stepsEl.innerHTML = labels.map((lbl, i) => {
                const ok = data.checklist[i];
                return `<div class="ict-step ${ok ? 'pass' : ''}">${lbl}</div>`;
            }).join('');
        }
        if (data.grade) {
            _setEl('ict-grade-badge', data.grade);
            const badge = document.getElementById('ict-grade-badge');
            if (badge) badge.className = `chip ${ data.grade.startsWith('A') ? 'chip-green' : data.grade === 'B' ? 'chip-gold' : 'chip-dim' }`;
        }
    }

    onConfluence(data) {
        if (data.total === undefined) return;
        const score = data.total;
        _setEl('confluence-score', score.toFixed(1));
        _setEl('ticker-score', score.toFixed(1));
        const fillEl = document.getElementById('confluence-fill');
        if (fillEl) fillEl.style.width = ((score / (data.maximum || 12)) * 100) + '%';

        const chip = document.getElementById('trade-signal-chip');
        if (chip) {
            const isSetup = score >= 5;
            chip.textContent  = isSetup ? '🎯 SETUP' : 'NO TRADE';
            chip.className    = 'chip ' + (isSetup ? 'chip-green' : 'chip-red');
            chip.style.cssText = '';
        }

        if (data.factors) {
            const fEl = document.getElementById('confluence-factors');
            if (fEl) {
                fEl.innerHTML = data.factors.slice(0, 6).map(f =>
                    `<div style="display:flex;justify-content:space-between;padding:3px 0;">
                        <span style="color:var(--c-text-2);">${f.name}</span>
                        <span style="color:${f.score > 0 ? 'var(--c-green)' : 'var(--c-text-3)'};">${f.score > 0 ? '+' + f.score.toFixed(1) : '—'}</span>
                    </div>`
                ).join('');
            }
        }
    }

    onHealth(data) {
        const src = data.current_source || '—';
        _setEl('feed-source', src);
        const feedChip = document.getElementById('feed-chip');
        if (feedChip) feedChip.className = 'chip ' + (data.primary?.connected ? 'chip-green' : 'chip-red');

        // Update Telegram status bar
        const tgBar  = document.getElementById('tg-status-bar');
        const tgText = document.getElementById('tg-status-text');
        if (data.telegram !== undefined && tgBar && tgText) {
            tgBar.className = 'tg-status ' + (data.telegram ? 'ok' : 'err');
            tgText.textContent = data.telegram ? '✅ Telegram connected — alerts will be sent live' : '❌ Telegram not configured — add BOT_TOKEN & CHAT_ID to .env';
        }
    }

    onIndicators(data) {
        if (data.atr_h1 !== undefined) {
            const atr = parseFloat(data.atr_h1).toFixed(2);
            _setEl('atr-value', '$' + atr);
        }
        _setEl('ticker-dir', data.direction || '—');
    }

    onFullState(data) {
        Object.assign(this.state, data);

        if (data.session) {
            _setEl('session-name', data.session.session_label || '—');
            const kz = document.getElementById('kz-timer');
            if (kz) {
                kz.textContent = data.session.killzone_active
                    ? `● ${data.session.killzone_name} ${data.session.killzone_remaining_min}m`
                    : data.session.session_label || '—';
                kz.className = data.session.killzone_active ? 'pos' : '';
            }
        }

        if (data.macro_bias) {
            _setEl('macro-bias', data.macro_bias);
        }

        if (data.account) {
            const pnl = data.account.weekly_pnl || 0;
            _setEl('weekly-pnl', pnl.toFixed(0));
            _setEl('daily-pnl', '$' + (data.account.daily_pnl || 0).toFixed(0));
            _setEl('trades-today', data.account.trades_today || 0);
            const prog = document.getElementById('weekly-progress');
            if (prog) prog.style.width = Math.min(100, (pnl / 300) * 100) + '%';
        }

        if (data.indicators) {
            _setEl('bsl-target', data.indicators.bsl || '—');
            _setEl('ssl-level',  data.indicators.ssl || '—');
            _setEl('h1-fvg',     data.indicators.fvg_h1 || '—');
            _setEl('m15-ob',     data.indicators.ob_m15 || '—');
        }
    }
}

// ── Boot ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    window.analyst = new GoldAnalystSSE();
});
