/* ═══════════════════════════════════════════════════════
   AURUM — Global Tab + UI Controller + SSE Client
   ═══════════════════════════════════════════════════════ */

'use strict';

// ── Timeframe Management ────────────────────────────────
function switchMainTimeframe(tf) {
    console.log(`[UI] Context switch to ${tf} priority`);
    // Update button states
    document.querySelectorAll('.tf-btn').forEach(btn => {
        btn.classList.toggle('active', btn.id === `tf-${tf}`);
    });
    const tfChip = document.getElementById('matrix-tf-chip');
    if (tfChip) tfChip.textContent = `${tf} LIVE`;
}

// ── Strategy Mode Toggle ────────────────────────────────
window.currentStrategyMode = 'swing';

function setUIMode(mode) {
    window.currentStrategyMode = mode;
    const swingBtn = document.getElementById('btn-mode-swing');
    const scalpBtn = document.getElementById('btn-mode-scalp');
    if (swingBtn) {
        swingBtn.style.background = mode === 'swing' ? 'var(--amber)' : 'transparent';
        swingBtn.style.color      = mode === 'swing' ? '#000' : '#aaa';
    }
    if (scalpBtn) {
        scalpBtn.style.background = mode === 'scalp' ? 'var(--amber)' : 'transparent';
        scalpBtn.style.color      = mode === 'scalp' ? '#000' : '#aaa';
    }
    // Re-render with current data if available
    if (window.lastConfluenceData && window.analyst) {
        window.analyst.onConfluence(window.lastConfluenceData);
    }
}

// ── Tab Management ─────────────────────────────────────
const TABS = ['terminal', 'charts', 'backtest'];

function switchTab(id) {
    TABS.forEach(t => {
        const view = document.getElementById('view-' + t);
        const btn  = document.getElementById('tab-' + t);
        if (view) view.style.display = t === id ? 'block' : 'none';
        if (btn)  btn.classList.toggle('active', t === id);
    });
    if (id === 'charts') initChartTab();
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

// ── Auto Backtest ───────────────────────────────────────
function runAutoBacktest() {
    const btn       = document.getElementById('btn-run-bt');
    const tf        = document.getElementById('bt-timeframe')?.value;
    const startDate = document.getElementById('bt-start-date')?.value;
    const endDate   = document.getElementById('bt-end-date')?.value;

    if (!tf) { showBanner('Select a timeframe first.'); return; }

    document.getElementById('bt-results-area').style.display = 'none';

    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Running...';

    fetch('/api/backtest/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ timeframe: tf, start_date: startDate, end_date: endDate, strategy: 'dor_asw' })
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

    const weeklyEl = document.getElementById('bt-stat-weekly');
    if (weeklyEl && data.weekly_avg) {
        weeklyEl.textContent = data.weekly_avg;
        const wNum = parseFloat((data.weekly_avg || '0').replace('$', ''));
        weeklyEl.style.color = wNum >= 0 ? 'var(--c-green)' : 'var(--c-red)';
    }

    // Fetch full trade-by-trade results from CSV
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
        const isLong = r.direction === 'long';
        const res = (r.result || '').toLowerCase();
        const isWin = res === 'win';
        const isBe  = res === 'be';
        const isPartial = res === 'partial';
        const resLabel = isWin ? 'WIN' : isBe ? 'BE' : (isPartial ? 'PARTIAL' : 'LOSS');
        const resChip  = isWin ? 'chip-green' : (isBe || isPartial) ? 'chip-dim' : 'chip-red';

        const entryDt = _fmtShortDate(r.timestamp);
        const exitDt  = r.exit_time ? _fmtShortDate(r.exit_time) : '—';
        const pnl = parseFloat(r.pnl || 0);
        
        const setup = r.setup_reason || 'Manual';
        const exitReason = r.exit_reason ? `<div style="font-size:9px; color:var(--c-text-3); margin-top:2px;">${r.exit_reason}</div>` : '';

        return `<tr>
            <td>
                <div style="font-weight:700;">$${parseFloat(r.price || 0).toFixed(2)}</div>
                <div style="font-size:10px; color:var(--c-text-3);">${entryDt}</div>
            </td>
            <td>
                <div style="font-weight:700;">$${parseFloat(r.exit_price || 0).toFixed(2)}</div>
                <div style="font-size:10px; color:var(--c-text-3);">${exitDt}</div>
            </td>
            <td style="color:${isLong ? 'var(--c-green)' : 'var(--c-red)'}; font-weight:700;">${isLong ? '↑ LONG' : '↓ SHORT'}</td>
            <td><span class="chip chip-dim" style="font-size:9px;">${r.timeframe || 'M5'}</span></td>
            <td>
                <div style="font-size:11px;">${setup}</div>
                <div style="font-size:9px; color:var(--c-gold); opacity:0.8;">${r.risk_factors || ''}</div>
            </td>
            <td>
                <span class="chip ${resChip}">${resLabel}</span>
                ${exitReason}
            </td>
            <td style="color:${pnl >= 0 ? 'var(--c-green)' : 'var(--c-red)'}; font-weight:700;">$${pnl.toFixed(2)}</td>
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
            const hint = document.getElementById('psych-hint');
            if (hint) { hint.textContent = 'REPORT READY TO GENERATE'; hint.style.color = 'var(--green)'; }
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
    if (el) el.innerHTML = val;
}

function _fmtDate(ts) {
    if (!ts) return '—';
    try {
        const d = isNaN(ts) ? new Date(ts) : new Date(Number(ts) * 1000);
        if (isNaN(d.getTime())) return '—';
        return d.toLocaleString('en-IN', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' });
    } catch (e) {
        return '—';
    }
}

function _fmtShortDate(ts) {
    if (!ts) return '—';
    try {
        const d = isNaN(ts) ? new Date(ts) : new Date(Number(ts) * 1000);
        if (isNaN(d.getTime())) return '—';
        return d.getDate() + '/' + (d.getMonth()+1) + ' ' + d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0');
    } catch (e) {
        return '—';
    }
}

// ═══════════════════════════════════════════════════════
//  Live SSE Client
// ═══════════════════════════════════════════════════════
class GoldAnalystSSE {
    constructor() {
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

    connect() {
        this.es = new EventSource('/api/stream');

        this.es.addEventListener('tick',              e => this.onTick(JSON.parse(e.data)));
        this.es.addEventListener('confluence_update', e => this.onConfluence(JSON.parse(e.data)));
        this.es.addEventListener('strategy_history',  e => this.onStrategyHistory(JSON.parse(e.data)));
        this.es.addEventListener('strategy_update',   e => this.onStrategyUpdate(JSON.parse(e.data)));
        this.es.addEventListener('health',            e => this.onHealth(JSON.parse(e.data)));
        this.es.addEventListener('full_state',        e => this.onFullState(JSON.parse(e.data)));
        this.es.addEventListener('indicators',           e => this.onIndicators(JSON.parse(e.data)));
        this.es.addEventListener('market_regime',        e => this.renderRegime(JSON.parse(e.data)));
        this.es.addEventListener('dealing_range_update', e => this.onDealingRange(JSON.parse(e.data)));
        this.es.addEventListener('live_trades',          e => this.onLiveTrades(JSON.parse(e.data)));
        this.es.addEventListener('account_update',       e => this.onAccountUpdate(JSON.parse(e.data)));

        this.es.onopen  = () => {
            this.setStatus(true);
            this.fetchHistory(); // Fetch initial history on open
        };
        this.es.onerror = () => {
            this.setStatus(false);
            setTimeout(() => this.connect(), 5000);
        };
    }

    async fetchHistory() {
        try {
            const resp = await fetch('/api/strategy/history');
            const data = await resp.json();
            this.onStrategyHistory(data);
        } catch (e) { console.warn('[SSE] History fetch failed:', e); }
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
        // Forward to chart
        if (window.aurumChart) {
            window.aurumChart.onTick(data.price, data.timestamp || Math.floor(Date.now() / 1000));
        }
    }
    
    onStrategyUpdate(data) {
        if (data.confluence) {
            this.onConfluence(data.confluence);
        }
        if (data.dr) {
            this.renderDealingRange(data.dr);
        }
        if (data.levels) {
            this.renderInstitutionalLevels(data.levels);
        }
    }

    renderDealingRange(dr) {
        if (!dr || !dr.is_valid) {
            _setEl('dr-high', '—');
            _setEl('dr-low',  '—');
            _setEl('dr-eq',   '—');
            _setEl('dr-ote',  'None in range');
            return;
        }
        _setEl('dr-high', '$' + dr.range_high.toFixed(2));
        _setEl('dr-low',  '$' + dr.range_low.toFixed(2));
        _setEl('dr-eq',   '$' + dr.equilibrium.toFixed(2));
        _setEl('dr-ote',  `$${dr.ote_low.toFixed(2)} – $${dr.ote_high.toFixed(2)}`);
    }

    renderInstitutionalLevels(lc) {
        if (!lc) return;
        _setEl('bsl-target', lc.bsl ? '$' + lc.bsl.toFixed(2) : 'None in range');
        _setEl('ssl-level',  lc.ssl ? '$' + lc.ssl.toFixed(2) : 'None in range');
        
        if (lc.fvg) {
            _setEl('h1-fvg', `${lc.fvg.direction === 'bullish' ? 'Bullish' : 'Bearish'} $${lc.fvg.low.toFixed(2)}–$${lc.fvg.high.toFixed(2)} (${lc.fvg.size?.toFixed(2) || 0} pts)`);
        } else {
            _setEl('h1-fvg', 'None in range');
        }
        
        if (lc.ob) {
            const status = lc.ob.status ? ` <span class="ob-status ${lc.ob.status.toLowerCase()}">(${lc.ob.status})</span>` : '';
            _setEl('m15-ob', `$${lc.ob.low.toFixed(2)}–$${lc.ob.high.toFixed(2)}${status}`);
        } else {
            _setEl('m15-ob', 'None in range');
        }
    }

    onConfluence(data) {
        if (!data || !data.swing) return;
        window.lastConfluenceData = data;
        
        const mode = window.currentStrategyMode;
        
        let score = 0;
        let max_score = 6.5;
        let isSetup = false;
        let isWatching = false;
        _setEl('ticker-dir', data.direction || '—');

        const chip = document.getElementById('trade-signal-chip');
        const matrixStatus = document.getElementById('matrix-status-chip');
        const actionText = document.getElementById('matrix-action-text');
        
        if (mode === 'swing') {
            score = data.swing.score;
            max_score = data.swing.max_score || 6.5;
            isSetup = data.swing.is_valid;
            isWatching = score >= 4.0;
            
            _setEl('confluence-score', score.toFixed(1));
            _setEl('ticker-score', score.toFixed(1));
            
            const fillEl = document.getElementById('confluence-fill');
            if (fillEl) fillEl.style.width = Math.min((score / max_score) * 100, 100) + '%';
            
            this.renderMatrix(data.swing.factors);
            
            if (chip) {
                chip.textContent = isSetup ? '🎯 SWING READY' : (isWatching ? '⚠️ WATCHING' : 'NO TRADE');
                chip.className   = 'chip ' + (isSetup ? 'chip-gold' : (isWatching ? 'chip-green' : 'chip-red'));
            }
            if (matrixStatus) {
                matrixStatus.textContent = isSetup ? '🎯 SWING READY' : (isWatching ? '⚠️ SWING WATCH' : 'SCANNING');
                matrixStatus.className = 'chip ' + (isSetup ? 'chip-gold' : (isWatching ? 'chip-green' : 'chip-dim'));
            }
            if (actionText) {
                actionText.textContent = isSetup ? '🎯 ENTRY READY' : (isWatching ? '⏳ WAITING FOR SWING ALIGNMENT' : '💤 NO SWING SETUP');
                actionText.style.color = isSetup ? 'var(--bull)' : 'var(--amber)';
            }
            
        } else if (mode === 'scalp') {
            score = 0;
            if (data.scalp.gates.bias.pass) score++;
            if (data.scalp.gates.setup.pass) score++;
            if (data.scalp.gates.trigger.pass) score++;
            
            max_score = 3;
            isSetup = data.scalp.is_valid;
            isWatching = score >= 2;
            
            _setEl('confluence-score', `${score} / 3`);
            _setEl('ticker-score', `${score} Gates`);
            
            const fillEl = document.getElementById('confluence-fill');
            if (fillEl) fillEl.style.width = Math.min((score / max_score) * 100, 100) + '%';
            
            this.renderScalpMatrix(data.scalp.gates);
            
            if (chip) {
                chip.textContent = isSetup ? '🎯 SCALP READY' : (isWatching ? '⚠️ SCALP WATCH' : 'NO SCALP');
                chip.className   = 'chip ' + (isSetup ? 'chip-gold' : (isWatching ? 'chip-green' : 'chip-red'));
            }
            if (matrixStatus) {
                matrixStatus.textContent = isSetup ? '🎯 SCALP READY' : (isWatching ? '⚠️ SCALP WATCH' : 'SCANNING');
                matrixStatus.className = 'chip ' + (isSetup ? 'chip-gold' : (isWatching ? 'chip-green' : 'chip-dim'));
            }
            if (actionText) {
                actionText.textContent = isSetup ? '🎯 ENTRY CONFIRMED' : (isWatching ? '⏳ WAITING FOR M5 TRIGGER' : '💤 NO SCALP FORMED');
                actionText.style.color = isSetup ? 'var(--bull)' : 'var(--amber)';
            }
        }

        // London Setup Alert
        const londonBanner = document.getElementById('london-setup-alert');
        if (londonBanner) {
            if (data.london_potential) {
                londonBanner.textContent = data.london_msg;
                londonBanner.style.display = 'block';
            } else {
                londonBanner.style.display = 'none';
            }
        }
        
        // Render Mini Factors List (uses Swing factors for baseline logic view)
        if (data.swing && data.swing.factors) {
            const fEl = document.getElementById('confluence-factors');
            if (fEl) {
                const factorsArr = Object.entries(data.swing.factors).map(([key, val]) => ({
                    name: key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
                    ...val
                }));
                fEl.innerHTML = factorsArr.slice(0, 5).map(f =>
                    `<div style="display:flex;justify-content:space-between;padding:2px 0;">
                        <span>${f.name}</span>
                        <span style="color:${f.score > 0 ? 'var(--bull)' : 'var(--t3)'};">${f.score > 0 ? '✓' : '✗'}</span>
                    </div>`
                ).join('');
            }
        }
    }

    renderMatrix(factors) {
        const body = document.getElementById('matrix-body');
        if (!body) return;

        const rows = Object.entries(factors).map(([key, f]) => {
            const name = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            const passed = f.score > 0;
            const status = passed ? '✅' : '❌';
            const cls = passed ? 'passed' : 'failed';
            const scoreText = f.score > 0 ? `+${f.score.toFixed(1)}` : '0.0';
            
            return `
                <div class="matrix-row ${cls}">
                    <div class="matrix-status">${status}</div>
                    <div class="matrix-label">${name}</div>
                    <div class="matrix-score">${scoreText}</div>
                    <div class="matrix-detail">${f.detail || 'No confluence detected'}</div>
                </div>
            `;
        });

        body.innerHTML = rows.join('');
    }

    renderScalpMatrix(gates) {
        const body = document.getElementById('matrix-body');
        if (!body) return;

        const rows = Object.entries(gates).map(([key, gate]) => {
            const labels = { bias: 'GATE 1: H1 Bias', setup: 'GATE 2: M15 Setup', trigger: 'GATE 3: M5 Trigger', killzone: 'GATE 4: Killzone' };
            const name = labels[key] || key.toUpperCase();
            const passed = gate.pass;
            const status = gate.status || (passed ? '✅' : '❌');
            const cls = passed ? 'passed' : 'failed';
            
            return `
                <div class="matrix-row ${cls}">
                    <div class="matrix-status">${status}</div>
                    <div class="matrix-label">${name}</div>
                    <div class="matrix-score">${passed ? 'PASS' : 'FAIL'}</div>
                    <div class="matrix-detail">${gate.detail || ''}</div>
                </div>
            `;
        });

        body.innerHTML = rows.join('');
    }

    onStrategyHistory(history) {
        const log = document.getElementById('strategy-history-log');
        const count = document.getElementById('history-count');
        if (!log) return;

        if (count) count.textContent = `${history.length} SCANS`;

        if (!history || history.length === 0) {
            log.innerHTML = '<div class="empty-state">Waiting for the next candle close to begin logging history...</div>';
            return;
        }

        log.innerHTML = history.map(h => {
            const swing = h.confluence && h.confluence.swing;
            const score = swing ? (swing.score || 0) : (h.confluence && h.confluence.total || 0);
            const maxScore = swing ? (swing.max_score || 6.5) : 6.5;
            const isGlow = swing ? swing.is_valid : score >= 8;
            return `
                <div class="history-item">
                    <div class="hist-main">
                        <div class="hist-time">${h.time_ist} IST — $${h.price}</div>
                        <div class="hist-setup">${h.setup_status || 'Scanning...'}</div>
                    </div>
                    <div class="hist-pnl" style="color:${isGlow ? 'var(--bull)' : 'var(--t2)'}">
                        ${score.toFixed(1)}/${maxScore}
                    </div>
                </div>
            `;
        }).join('');
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
        
        // Institutional Levels (Fallback from direct indicators event)
        if (data.liquidity_pools) {
            const bsl = data.liquidity_pools.find(p => p.type === 'BSL');
            const ssl = data.liquidity_pools.find(p => p.type === 'SSL');
            if (bsl) _setEl('bsl-target', '$' + bsl.price.toFixed(2));
            if (ssl) _setEl('ssl-level',  '$' + ssl.price.toFixed(2));
        }
        if (data.fvgs_h1 && data.fvgs_h1.length) {
            const fvg = data.fvgs_h1[data.fvgs_h1.length - 1];
            _setEl('h1-fvg', `$${fvg.low.toFixed(2)}–$${fvg.high.toFixed(2)}`);
        }
        if (data.obs_m15 && data.obs_m15.length) {
            const ob = data.obs_m15[data.obs_m15.length - 1];
            _setEl('m15-ob', `$${ob.low.toFixed(2)}–$${ob.high.toFixed(2)}`);
        }
        _setEl('ticker-dir', data.direction || '—');
        // Cache indicator data for chart overlay merging
        window._lastIndicatorData = data;
        this._refreshChartOverlays();
    }

    onDealingRange(data) {
        if (!data) return;
        window._lastDRData = data;
        // Also update DR display (already handled by confluence but as fallback)
        this._refreshChartOverlays();
    }

    _refreshChartOverlays() {
        if (!window.aurumChart || !window.aurumChart._ready) return;
        const ind = window._lastIndicatorData || {};
        const dr  = window._lastDRData || {};
        window.aurumChart.refreshOverlays({
            fvgs_h1:  ind.fvgs_h1  || [],
            fvgs_m15: ind.fvgs_m15 || [],
            fvgs_m5:  ind.fvgs_m5  || [],
            obs_h4:   ind.obs_h4   || [],
            obs_h1:   ind.obs_h1   || [],
            obs_m15:  ind.obs_m15  || [],
            obs_m5:   ind.obs_m5   || [],
            swing_highs_h1:  ind.swing_highs_h1  || [],
            swing_lows_h1:   ind.swing_lows_h1   || [],
            liquidity_pools: ind.liquidity_pools  || [],
            dealing_range: dr.is_valid ? {
                high:     dr.range_high,
                low:      dr.range_low,
                eq:       dr.equilibrium,
                ote_high: dr.ote_high,
                ote_low:  dr.ote_low,
            } : null,
        });
    }
    
    renderRegime(data) {
        if (!data) return;
        const name = data.regime_type || 'SCANNING';
        const color = data.hard_lock ? 'var(--c-red)' : 'var(--c-gold)';
        
        _setEl('regime-value', name);
        const rv = document.getElementById('regime-value');
        if (rv) rv.style.color = color;

        _setEl('hard-lock-status', data.hard_lock ? 'ACTIVE' : 'OFF');
        const hls = document.getElementById('hard-lock-status');
        if (hls) {
            hls.style.color = data.hard_lock ? 'var(--c-red)' : 'var(--c-green)';
            hls.className = data.hard_lock ? 'blink' : '';
        }

        _setEl('regime-name', name.replace(/_/g, ' '));
        _setEl('regime-desc', data.description || '');
        _setEl('ui-adx', data.adx_h1 ? data.adx_h1.toFixed(2) : '—');
        _setEl('ui-ema-cross', data.ema_20_50_cross || 'neutral');
        _setEl('ui-momentum', data.candle_body_to_range ? (data.candle_body_to_range * 100).toFixed(1) + '%' : '—');
        
        const chip = document.getElementById('regime-chip');
        if (chip) {
            chip.textContent = data.hard_lock ? 'NO TRADE' : 'ANALYZED';
            chip.className = 'chip ' + (data.hard_lock ? 'chip-red' : 'chip-gold');
        }
    }
    
    onMacro(data) {
        if (data.macro_bias) {
            _setEl('macro-bias', data.macro_bias);
        }
        if (data.dxy_value) {
            const val = data.dxy_value + (data.dxy_dir ? ' (' + data.dxy_dir + ')' : '');
            _setEl('dxy-value', val);
        }
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

        if (data.macro) {
            this.onMacro(data.macro);
        }

        if (data.account) {
            this.onAccountUpdate(data.account);
        }

        if (data.indicator_update) {
            this.onIndicators(data.indicator_update);
        }
        if (data.market_regime) {
            this.renderRegime(data.market_regime);
        }
        if (data.strategy_update) {
            this.onStrategyUpdate(data.strategy_update);
        }

        if (data.health) {
            this.onHealth(data.health);
        }

        if (data.confluence_update) {
            this.onConfluence(data.confluence_update);
        }

        if (data.strategy_history) {
            this.onStrategyHistory(data.strategy_history);
        }

        if (data.dealing_range_update) {
            this.onDealingRange(data.dealing_range_update);
        }

        if (data.indicators) {
            this.onIndicators(data.indicators);
        }

        if (data.live_trades) {
            this.onLiveTrades(data.live_trades);
        }

        if (data.account_update) {
            this.onAccountUpdate(data.account_update);
        }
    }

    onAccountUpdate(data) {
        const pnl = data.weekly_pnl || 0;
        _setEl('weekly-pnl', (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(0));
        _setEl('daily-pnl', (data.daily_pnl >= 0 ? '+$' : '-$') + Math.abs(data.daily_pnl || 0).toFixed(0));
        _setEl('trades-today', data.trades_today || 0);
        const pnlBig = document.getElementById('weekly-pnl-display');
        if (pnlBig) pnlBig.className = 'pnl-big ' + (pnl > 0 ? 'pos' : pnl < 0 ? 'neg' : '');
        const prog = document.getElementById('weekly-progress');
        if (prog) prog.style.width = Math.min(100, Math.max(0, (pnl / 300) * 100)) + '%';
    }

    onLiveTrades(data) {
        const pending    = data.pending_setup;
        const signals    = data.open_signals   || [];
        const alertLog   = data.alert_log      || [];
        const statusChip = document.getElementById('live-trade-status-chip');
        const pendingBox = document.getElementById('live-pending-box');
        const openDiv    = document.getElementById('live-open-signals');
        const logDiv     = document.getElementById('live-alert-log');

        // ── Status chip ──
        if (statusChip) {
            if (signals.length > 0) {
                statusChip.textContent = `${signals.length} OPEN`;
                statusChip.className = 'chip chip-green';
            } else if (pending) {
                statusChip.textContent = 'PENDING';
                statusChip.className = 'chip chip-amber';
            } else {
                statusChip.textContent = 'NO SIGNAL';
                statusChip.className = 'chip chip-dim';
            }
        }

        // ── Pending setup ──
        if (pendingBox) {
            if (pending) {
                pendingBox.style.display = 'block';
                const d = document.getElementById('live-pending-detail');
                if (d) d.innerHTML =
                    `<span style="color:#f59e0b">${pending.tf || 'M5'} · ${pending.mode || '—'}</span>  ${(pending.direction||'').toUpperCase()}<br>` +
                    `MT Entry: <b style="color:var(--t1)">$${(pending.mt_price || 0).toFixed(2)}</b>  ` +
                    `@ ${pending.time_ist || '—'}<br>` +
                    `Bars waited: ${pending.bars_waited || 0} / 3`;
            } else {
                pendingBox.style.display = 'none';
            }
        }

        // ── Open signals ──
        if (openDiv) {
            if (signals.length === 0) {
                openDiv.innerHTML = '';
            } else {
                openDiv.innerHTML = signals.map(s => {
                    const isLong  = (s.direction || '').includes('bullish');
                    const arrow   = isLong ? '↑' : '↓';
                    const clr     = isLong ? '#00ffa3' : '#ff2d6b';
                    const partial = s.partial_hit ? ' · <span style="color:#f59e0b">1R HIT — BE</span>' : '';
                    return `<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);border-radius:6px;padding:10px;margin-bottom:6px;font-family:'Space Mono',monospace;font-size:10px;line-height:1.9;">
                        <div style="color:${clr};font-size:11px;margin-bottom:4px;">${arrow} ${(s.direction||'').toUpperCase()} &nbsp;<span style="color:var(--t3)">${s.tf||'M5'} · ${s.mode||''}</span>${partial}</div>
                        <div>Entry <b style="color:var(--t1)">$${(s.entry||0).toFixed(2)}</b> &nbsp;·&nbsp; ${s.entry_time || ''}</div>
                        <div>SL <span style="color:#ff2d6b">$${(s.sl||0).toFixed(2)}</span> &nbsp;·&nbsp; TP <span style="color:#00ffa3">$${(s.tp||0).toFixed(2)}</span> &nbsp;·&nbsp; ${s.lots} lots</div>
                    </div>`;
                }).join('');
            }
        }

        // ── Alert log ──
        if (logDiv) {
            if (alertLog.length === 0) {
                logDiv.innerHTML = '<div style="font-size:10px;color:var(--t3);font-family:\'Space Mono\',monospace;">No alerts yet</div>';
            } else {
                const icons = { entry: '💎', partial_tp: '💰', tp_hit: '🏆', sl_hit: '🛑', be_exit: '⚪' };
                logDiv.innerHTML = alertLog.map(a => {
                    const icon    = icons[a.type] || '•';
                    const pnlStr  = a.pnl != null ? ` &nbsp;<b style="color:${a.pnl>=0?'#00ffa3':'#ff2d6b'}">${a.pnl>=0?'+':''}$${a.pnl}</b>` : '';
                    const priceStr = a.price != null ? ` @ $${(+a.price).toFixed(2)}` : '';
                    return `<div style="display:flex;justify-content:space-between;font-size:10px;font-family:'Space Mono',monospace;color:var(--t2);padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.04);">
                        <span>${icon} ${a.type.replace('_',' ').toUpperCase()}${priceStr}${pnlStr}</span>
                        <span style="color:var(--t3)">${a.time || ''}</span>
                    </div>`;
                }).join('');
            }
        }
    }
}

// ── Boot ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    window.analyst = new GoldAnalystSSE();
});
