import { api } from './api.js';
import { showToast, showModal } from './app.js';

const container = document.getElementById('routes');

const STATUS_LABELS = {
    completed: '完成', cancelled: '取消', failed: '失敗',
    queued: '排隊中', assigned: '已指派', running: '執行中',
    offline_running: '離線執行中',
};
const STATUS_COLORS = {
    completed: 'var(--success)', cancelled: 'var(--warning)', failed: 'var(--coral)',
    queued: 'var(--text-muted)', assigned: 'var(--amber)', running: 'var(--amber)',
    offline_running: 'var(--teal)',
};

let _robots = [];
let _buttons = [];
let _locations = [];
let _routeMode = 'online';

export async function initRoutes(ws) {
    ws.on('route:assigned', () => renderActiveRuns());
    ws.on('route:queued', () => renderActiveRuns());
    ws.on('route:moving', () => renderActiveRuns());
    ws.on('route:arrived', () => renderActiveRuns());
    ws.on('route:confirmed', () => renderActiveRuns());
    ws.on('route:timeout', () => renderActiveRuns());
    ws.on('route:finishing', () => renderActiveRuns());
    ws.on('route:completed', () => { renderActiveRuns(); renderHistory(); });
    ws.on('route:cancelled', () => { renderActiveRuns(); renderHistory(); });
    ws.on('route:failed', () => { renderActiveRuns(); renderHistory(); });
    ws.on('route:waiting', (data) => updateCountdown(data));
    ws.on('route:offline_started', () => renderActiveRuns());
    ws.on('route:offline_report', () => renderActiveRuns());
    await renderAll();
}

// ── Helpers ──────────────────────────────────────────────────────────

function fmtTime(iso) {
    if (!iso) return '--';
    return new Date(iso).toLocaleString('zh-TW', { hour12: false });
}

function fmtShortTime(iso) {
    if (!iso) return '--';
    return new Date(iso).toLocaleTimeString('zh-TW', { hour12: false });
}

let _shelves = [];

async function loadMeta() {
    try {
        const [robots, buttons] = await Promise.all([api.listRobots(), api.listButtons()]);
        _robots = robots;
        _buttons = buttons;
        // Gather locations + shelves from first online robot
        const online = robots.find(r => r.online);
        if (online) {
            try {
                const d = await api.getLocations(online.id);
                _locations = d.locations || [];
            } catch { _locations = []; }
            try {
                const d = await api.getShelves(online.id);
                _shelves = d.shelves || [];
            } catch { _shelves = []; }
        } else {
            _locations = [];
            _shelves = [];
        }
    } catch { /* ignore */ }
}

function robotName(id) {
    const r = _robots.find(r => r.id === id);
    return r ? r.name : (id || '--');
}

function buttonName(id) {
    if (id == null) return null;
    const b = _buttons.find(b => b.id === id || b.id === String(id));
    return b ? (b.name || b.ieee_addr) : `#${id}`;
}

// ── Stop Picker (toggle buttons + drag reorder) ────────────────────

function createStopPicker(containerEl, selectedStops) {
    /**
     * Renders a toggle-button grid of all locations (4 per row).
     * Selected stops appear in a draggable ordered list below.
     * Mutates `selectedStops` array in place.
     * Returns { refresh() } to re-render.
     */
    function render() {
        const selectedNames = new Set(selectedStops.map(s => s.name));
        containerEl.innerHTML = `
            <div class="loc-grid" style="display:grid;grid-template-columns:repeat(4,1fr);gap:0.4rem;margin-bottom:0.75rem">
                ${_locations.map(l => {
                    const active = selectedNames.has(l.name);
                    const idx = active ? selectedStops.findIndex(s => s.name === l.name) + 1 : null;
                    return `<button type="button" class="loc-toggle ${active ? 'loc-active' : ''}" data-name="${l.name}" style="
                        position:relative;padding:0.45rem 0.3rem;border-radius:4px;font-size:0.78rem;cursor:pointer;
                        font-family:var(--font-mono);text-align:center;transition:all 0.15s;
                        border:1px solid ${active ? 'var(--amber)' : 'var(--border-medium)'};
                        background:${active ? 'var(--amber-subtle)' : 'var(--panel-light)'};
                        color:${active ? 'var(--amber)' : 'var(--text-secondary)'};
                        font-weight:${active ? '600' : '400'};
                    ">${active ? `<span style="position:absolute;top:2px;left:4px;font-size:0.6rem;color:var(--amber-dim)">${idx}</span>` : ''}${l.name}</button>`;
                }).join('')}
            </div>
            <div class="stop-order" style="min-height:1.5rem">
                ${selectedStops.length === 0
                    ? '<p style="color:var(--text-muted);font-size:0.82rem">點選上方位置按鈕選擇停靠站</p>'
                    : `<div style="display:flex;flex-wrap:wrap;gap:0.35rem">${selectedStops.map((s, i) => `<div class="stop-chip" draggable="true" data-idx="${i}" style="
                        display:inline-flex;align-items:center;gap:0.3rem;padding:0.25rem 0.5rem;
                        border-radius:3px;font-size:0.78rem;cursor:grab;user-select:none;
                        background:var(--amber-subtle);border:1px solid var(--amber);color:var(--amber-dim);
                    "><span style="font-weight:600;min-width:1rem">${i + 1}.</span><span>${s.name}</span></div>`).join('')}</div>`}
            </div>`;

        // Toggle click
        containerEl.querySelectorAll('.loc-toggle').forEach(btn => {
            btn.onclick = (e) => {
                e.preventDefault();
                const name = btn.dataset.name;
                const idx = selectedStops.findIndex(s => s.name === name);
                if (idx >= 0) {
                    selectedStops.splice(idx, 1);
                } else {
                    selectedStops.push({ name });
                }
                render();
            };
        });

        // Drag reorder on chips
        let dragIdx = null;
        containerEl.querySelectorAll('.stop-chip').forEach(chip => {
            chip.addEventListener('dragstart', (e) => {
                dragIdx = parseInt(chip.dataset.idx);
                chip.style.opacity = '0.4';
                e.dataTransfer.effectAllowed = 'move';
            });
            chip.addEventListener('dragend', () => {
                chip.style.opacity = '1';
                dragIdx = null;
            });
            chip.addEventListener('dragover', (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                chip.style.borderColor = 'var(--amber-bright)';
            });
            chip.addEventListener('dragleave', () => {
                chip.style.borderColor = 'var(--amber)';
            });
            chip.addEventListener('drop', (e) => {
                e.preventDefault();
                const dropIdx = parseInt(chip.dataset.idx);
                if (dragIdx !== null && dragIdx !== dropIdx) {
                    const [moved] = selectedStops.splice(dragIdx, 1);
                    selectedStops.splice(dropIdx, 0, moved);
                    render();
                }
            });
        });
    }

    render();
    return { refresh: render };
}

// ── Mode Toggle & SSH Panel ──────────────────────────────────────────

function renderModeToggle() {
    const existing = document.getElementById('route-mode-toggle');
    if (existing) existing.remove();

    const div = document.createElement('div');
    div.id = 'route-mode-toggle';
    div.style.cssText = 'display:flex;align-items:center;gap:1rem;padding:0.75rem 1rem;margin-bottom:1rem;background:var(--panel-mid);border:1px solid var(--border-subtle)';
    div.innerHTML = `
        <span style="font-family:var(--font-display);font-size:0.75rem;font-weight:600;letter-spacing:1.5px;text-transform:uppercase;color:var(--text-secondary)">路線模式</span>
        <div style="display:flex;gap:0">
            <button class="mode-btn ${_routeMode === 'online' ? 'mode-active' : ''}" data-mode="online"
                style="padding:0.4rem 1rem;border:1px solid var(--border-subtle);background:${_routeMode === 'online' ? 'var(--amber-subtle)' : 'var(--void)'};color:${_routeMode === 'online' ? 'var(--amber)' : 'var(--text-muted)'};font-family:var(--font-display);font-size:0.7rem;font-weight:600;letter-spacing:1px;text-transform:uppercase;cursor:pointer">Online</button>
            <button class="mode-btn ${_routeMode === 'offline' ? 'mode-active' : ''}" data-mode="offline"
                style="padding:0.4rem 1rem;border:1px solid var(--border-subtle);border-left:none;background:${_routeMode === 'offline' ? 'var(--teal-subtle,rgba(0,139,114,0.08))' : 'var(--void)'};color:${_routeMode === 'offline' ? 'var(--teal)' : 'var(--text-muted)'};font-family:var(--font-display);font-size:0.7rem;font-weight:600;letter-spacing:1px;text-transform:uppercase;cursor:pointer">Offline</button>
        </div>
    `;
    div.querySelectorAll('.mode-btn').forEach(btn => {
        btn.onclick = async () => {
            const mode = btn.dataset.mode;
            try {
                await api.updateRouteMode({ mode });
                _routeMode = mode;
                renderModeToggle();
                renderSSHPanel();
            } catch (e) {
                showToast('切換失敗: ' + e.message, true);
            }
        };
    });
    container.prepend(div);
}

async function renderSSHPanel() {
    const existing = document.getElementById('ssh-panel');
    if (existing) existing.remove();
    if (_routeMode !== 'offline') return;

    const panel = document.createElement('div');
    panel.id = 'ssh-panel';
    panel.style.cssText = 'padding:0.75rem 1rem;margin-bottom:1rem;background:var(--panel-light);border:1px solid var(--border-subtle)';

    let html = '<div style="font-family:var(--font-display);font-size:0.7rem;font-weight:600;letter-spacing:1.5px;text-transform:uppercase;color:var(--text-secondary);margin-bottom:0.5rem">SSH 連線狀態</div>';

    for (const r of _robots) {
        html += `<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.4rem">
            <span style="font-size:0.8rem">${r.name} (${r.ip})</span>
            <span id="ssh-status-${r.id}" style="font-size:0.75rem;color:var(--text-muted)">—</span>
            <button onclick="window._testSSH('${r.id}')" style="font-size:0.7rem;padding:0.2rem 0.5rem;border:1px solid var(--border-subtle);background:var(--void);cursor:pointer;font-family:var(--font-mono)">測試</button>
        </div>`;
    }

    html += '<div id="ssh-key-display" style="display:none;margin-top:0.5rem;padding:0.5rem;background:var(--terminal-bg);border:1px solid var(--border-subtle);font-size:0.7rem;font-family:var(--font-mono);word-break:break-all"></div>';
    panel.innerHTML = html;

    const toggle = document.getElementById('route-mode-toggle');
    if (toggle) toggle.after(panel);
    else container.prepend(panel);
}

window._testSSH = async (robotId) => {
    const el = document.getElementById(`ssh-status-${robotId}`);
    if (el) el.textContent = '測試中...';
    try {
        const result = await api.testSSH({ robot_id: robotId });
        if (result.ok) {
            if (el) { el.textContent = '✓ OK'; el.style.color = 'var(--mint)'; }
        } else {
            if (el) { el.textContent = '✗ ' + (result.error || '失敗'); el.style.color = 'var(--coral)'; }
            showPublicKey();
        }
    } catch (e) {
        if (el) { el.textContent = '✗ ' + e.message; el.style.color = 'var(--coral)'; }
        showPublicKey();
    }
};

async function showPublicKey() {
    const display = document.getElementById('ssh-key-display');
    if (!display) return;
    try {
        const data = await api.getPublicKey();
        display.style.display = 'block';
        display.innerHTML = `<div style="color:var(--text-secondary);margin-bottom:0.3rem">請將以下公鑰加入機器人的 ~/.ssh/authorized_keys：</div><code>${data.public_key}</code>`;
    } catch {
        display.style.display = 'block';
        display.innerHTML = '<span style="color:var(--coral)">無法取得 SSH 公鑰</span>';
    }
}

// ── Full Render ──────────────────────────────────────────────────────

async function renderAll() {
    container.innerHTML = `
        <div id="rt-templates"></div>
        <div id="rt-dispatch"></div>
        <div id="rt-active"></div>
        <div id="rt-history"></div>`;
    try {
        const modeData = await api.getRouteMode();
        _routeMode = modeData.mode || 'online';
    } catch { _routeMode = 'online'; }
    await loadMeta();
    renderModeToggle();
    await renderSSHPanel();
    await Promise.all([
        renderTemplates(),
        renderQuickDispatch(),
        renderActiveRuns(),
        renderHistory(),
    ]);
}

// ── Templates Section ────────────────────────────────────────────────

async function renderTemplates() {
    const section = container.querySelector('#rt-templates');
    if (!section) return;
    let templates = [];
    try { templates = await api.listRouteTemplates(); } catch { /* ignore */ }

    section.innerHTML = `<div class="card">
        <div class="card-header"><h2>路線模板</h2><button class="btn btn-primary" id="add-template">+ 新增模板</button></div>
        ${templates.length === 0
            ? '<p style="color:var(--text-muted);text-align:center;padding:0.5rem 0">尚無路線模板</p>'
            : `<div class="table-wrap"><table><thead><tr>
                <th>名稱</th><th>停靠站</th><th>超時</th><th>綁定機器人</th><th>操作</th>
            </tr></thead><tbody>${templates.map(t => `<tr>
                <td>${t.name}</td>
                <td>${t.stops.map(s => s.name).join(' > ')}</td>
                <td style="color:var(--text-muted)">${t.default_timeout}s</td>
                <td style="color:var(--text-muted)">${t.pinned_robot_id ? robotName(t.pinned_robot_id) : '自動派遣'}</td>
                <td>
                    <button class="btn btn-sm btn-primary tpl-dispatch" data-id="${t.id}">出發</button>
                    <button class="btn btn-sm btn-primary tpl-edit" data-id="${t.id}">編輯</button>
                    <button class="btn btn-sm btn-danger tpl-del" data-id="${t.id}">刪除</button>
                </td>
            </tr>`).join('')}</tbody></table></div>`}
    </div>`;

    section.querySelector('#add-template').onclick = () => openTemplateModal(null);

    section.querySelectorAll('.tpl-dispatch').forEach(btn => {
        btn.onclick = async () => {
            try {
                await api.dispatchRoute({ template_id: btn.dataset.id });
                showToast('路線已派遣');
                await renderActiveRuns();
            } catch (e) { showToast(e.message, 'error'); }
        };
    });

    section.querySelectorAll('.tpl-edit').forEach(btn => {
        btn.onclick = async () => {
            const t = templates.find(t => t.id === btn.dataset.id);
            if (t) openTemplateModal(t);
        };
    });

    section.querySelectorAll('.tpl-del').forEach(btn => {
        btn.onclick = async () => {
            if (!confirm('確定刪除此模板？')) return;
            try {
                await api.deleteRouteTemplate(btn.dataset.id);
                showToast('模板已刪除');
                await renderTemplates();
            } catch (e) { showToast(e.message, 'error'); }
        };
    });
}

function openTemplateModal(existing) {
    const isEdit = !!existing;
    const title = isEdit ? '編輯路線模板' : '新增路線模板';
    let stops = existing ? [...existing.stops] : [];

    const bodyHtml = `
        <div class="form-group"><label>名稱</label><input id="tpl-name" value="${existing ? existing.name : ''}"></div>
        <div class="form-group"><label>搬運貨架</label><select id="tpl-shelf">
            <option value="">-- 選擇貨架 --</option>
            ${_shelves.map(s => `<option value="${s.name}" ${existing && existing.shelf_name === s.name ? 'selected' : ''}>${s.name}</option>`).join('')}
        </select></div>
        <div class="form-group"><label>綁定機器人</label><select id="tpl-robot">
            <option value="">自動派遣 (Round-Robin)</option>
            ${_robots.map(r => `<option value="${r.id}" ${existing && existing.pinned_robot_id === r.id ? 'selected' : ''}>${r.name}</option>`).join('')}
        </select></div>
        <div class="form-group"><label>確認按鈕</label><select id="tpl-confirm">
            <option value="">無 (純超時)</option>
            ${_buttons.map(b => `<option value="${b.id}" ${existing && String(existing.confirm_button_id) === String(b.id) ? 'selected' : ''}>${b.name || b.ieee_addr}</option>`).join('')}
        </select></div>
        <div class="form-group"><label>預設超時 (秒)</label><input id="tpl-timeout" type="number" value="${existing ? existing.default_timeout : 120}" min="1"></div>
        <div class="form-group"><label>停靠站 <span style="color:var(--text-muted);font-weight:400">(點選選擇，拖拉排序)</span></label>
            <div id="tpl-stop-picker"></div>
        </div>`;

    const overlay = showModal(title, bodyHtml, async (ol) => {
        const name = ol.querySelector('#tpl-name').value.trim();
        if (!name) { showToast('請輸入名稱', 'error'); return; }
        if (stops.length === 0) { showToast('請至少新增一個停靠站', 'error'); return; }
        if (!ol.querySelector('#tpl-shelf').value) { showToast('請選擇搬運貨架', 'error'); return; }
        const data = {
            name,
            stops: stops.map(s => ({ name: s.name })),
            default_timeout: parseInt(ol.querySelector('#tpl-timeout').value) || 120,
            pinned_robot_id: ol.querySelector('#tpl-robot').value || null,
            confirm_button_id: ol.querySelector('#tpl-confirm').value ? parseInt(ol.querySelector('#tpl-confirm').value) : null,
            shelf_name: ol.querySelector('#tpl-shelf').value || null,
        };
        try {
            if (isEdit) {
                await api.updateRouteTemplate(existing.id, data);
                showToast('模板已更新');
            } else {
                await api.createRouteTemplate(data);
                showToast('模板已建立');
            }
            await renderTemplates();
        } catch (e) { showToast(e.message, 'error'); }
    });

    // Wire up stop picker (toggle buttons + drag reorder)
    const pickerEl = overlay.querySelector('#tpl-stop-picker');
    if (pickerEl) createStopPicker(pickerEl, stops);
}

// ── Quick Dispatch Section ───────────────────────────────────────────

async function renderQuickDispatch() {
    const section = container.querySelector('#rt-dispatch');
    if (!section) return;

    let qdStops = [];

    section.innerHTML = `<div class="card">
        <div class="card-header"><h2>快速派遣</h2></div>
        <div class="form-group"><label>停靠站 <span style="color:var(--text-muted);font-weight:400">(點選選擇，拖拉排序)</span></label>
            <div id="qd-stop-picker"></div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem">
            <div class="form-group"><label>搬運貨架</label><select id="qd-shelf">
                <option value="">-- 選擇貨架 --</option>
                ${_shelves.map(s => `<option value="${s.name}">${s.name}</option>`).join('')}
            </select></div>
            <div class="form-group"><label>超時 (秒)</label><input id="qd-timeout" type="number" value="120" min="1"></div>
            <div class="form-group"><label>確認按鈕</label><select id="qd-confirm">
                <option value="">無 (純超時)</option>
                ${_buttons.map(b => `<option value="${b.id}">${b.name || b.ieee_addr}</option>`).join('')}
            </select></div>
            <div class="form-group"><label>指定機器人</label><select id="qd-robot">
                <option value="">自動派遣</option>
                ${_robots.map(r => `<option value="${r.id}">${r.name}</option>`).join('')}
            </select></div>
        </div>
        <div style="text-align:right"><button class="btn btn-primary" id="qd-go">立即出發</button></div>
    </div>`;

    const qdPickerEl = section.querySelector('#qd-stop-picker');
    if (qdPickerEl) createStopPicker(qdPickerEl, qdStops);

    section.querySelector('#qd-go').onclick = async () => {
        if (qdStops.length === 0) { showToast('請至少新增一個停靠站', 'error'); return; }
        if (!section.querySelector('#qd-shelf').value) { showToast('請選擇搬運貨架', 'error'); return; }
        const data = {
            stops: qdStops.map(s => ({ name: s.name })),
            default_timeout: parseInt(section.querySelector('#qd-timeout').value) || 120,
            confirm_button_id: section.querySelector('#qd-confirm').value ? parseInt(section.querySelector('#qd-confirm').value) : null,
            pinned_robot_id: section.querySelector('#qd-robot').value || null,
            shelf_name: section.querySelector('#qd-shelf').value || null,
        };
        try {
            await api.dispatchRoute(data);
            showToast('路線已派遣');
            qdStops.length = 0;
            qdPickerEl && createStopPicker(qdPickerEl, qdStops);
            await renderActiveRuns();
        } catch (e) { showToast(e.message, 'error'); }
    };
}

// ── Active Runs Section ──────────────────────────────────────────────

async function renderActiveRuns() {
    const section = container.querySelector('#rt-active');
    if (!section) return;

    let runs = [];
    try { runs = await api.listActiveRuns(); } catch { /* ignore */ }

    if (runs.length === 0) {
        section.innerHTML = `<div class="card">
            <div class="card-header"><h2>執行中路線</h2></div>
            <p style="color:var(--text-muted);text-align:center;padding:0.5rem 0">目前沒有執行中的路線</p>
        </div>`;
        return;
    }

    section.innerHTML = `<div class="card">
        <div class="card-header"><h2>執行中路線</h2></div>
        ${runs.map(run => {
            const stops = run.stops || [];
            const current = run.current_stop ?? -1;
            const total = stops.length;
            const pct = total > 0 ? Math.round(((current + 1) / total) * 100) : 0;
            const isOffline = run.execution_mode === 'offline' || run.status === 'offline_running';
            const barColor = isOffline ? 'var(--teal)' : 'var(--amber)';
            const nameColor = isOffline ? 'var(--teal)' : 'var(--amber)';
            const cancelBtn = isOffline
                ? `<button class="btn btn-sm btn-danger" disabled title="離線模式下請至機器人端手動停止" style="opacity:0.4;cursor:not-allowed">取消</button>`
                : `<button class="btn btn-sm btn-danger run-cancel" data-id="${run.id}">取消</button>`;
            const offlineBadge = isOffline
                ? `<span style="font-size:0.7rem;font-family:var(--font-display);letter-spacing:1px;text-transform:uppercase;color:var(--teal);border:1px solid var(--teal);padding:0.1rem 0.4rem;margin-left:0.5rem">${STATUS_LABELS.offline_running}</span>`
                : '';
            const reportLine = isOffline && run.last_report_time
                ? `<div style="font-size:0.78rem;color:var(--text-muted);margin-top:0.25rem">最後回報: ${fmtShortTime(run.last_report_time)}</div>`
                : '';

            return `<div class="route-run-card" data-run="${run.id}" style="border:1px solid var(--border-medium);border-radius:4px;padding:0.75rem;margin-bottom:0.75rem;background:var(--panel-mid)">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem">
                    <span style="font-weight:600;color:${nameColor}">${robotName(run.robot_id)}${offlineBadge}</span>
                    ${cancelBtn}
                </div>
                <div style="background:var(--border-subtle);border-radius:2px;height:6px;margin-bottom:0.5rem">
                    <div style="background:${barColor};height:100%;border-radius:2px;width:${pct}%;transition:width 0.3s"></div>
                </div>
                <div style="display:flex;flex-wrap:wrap;gap:0.3rem;margin-bottom:0.5rem;font-size:0.82rem">
                    ${stops.map((s, i) => {
                        let icon, color;
                        if (i < current) { icon = '\u2713'; color = 'var(--success)'; }
                        else if (i === current) { icon = '\u25cf'; color = isOffline ? 'var(--teal)' : 'var(--amber)'; }
                        else { icon = '\u25cb'; color = 'var(--text-muted)'; }
                        return `<span style="color:${color}">${icon} ${s.name}</span>`;
                    }).join('')}
                </div>
                <div class="countdown-display" data-run="${run.id}" style="font-size:0.82rem;color:var(--text-muted)"></div>
                ${reportLine}
            </div>`;
        }).join('')}
    </div>`;

    section.querySelectorAll('.run-cancel').forEach(btn => {
        btn.onclick = async () => {
            try {
                await api.cancelRoute(btn.dataset.id);
                showToast('路線已取消');
                await renderActiveRuns();
            } catch (e) { showToast(e.message, 'error'); }
        };
    });
}

function updateCountdown(data) {
    const el = container.querySelector(`.countdown-display[data-run="${data.run_id}"]`);
    if (!el) return;
    const remaining = data.remaining ?? 0;
    el.textContent = `停靠站 ${(data.stop_index ?? 0) + 1} -- 剩餘 ${remaining}s`;
}

// ── History Section ──────────────────────────────────────────────────

let _historyPage = 1;

async function renderHistory(page) {
    if (page != null) _historyPage = page;
    const section = container.querySelector('#rt-history');
    if (!section) return;

    let data = { runs: [], total: 0, page: 1, per_page: 20 };
    try { data = await api.getRouteHistory(_historyPage); } catch { /* ignore */ }
    const totalPages = Math.ceil(data.total / data.per_page) || 1;

    section.innerHTML = `<div class="card">
        <div class="card-header"><h2>路線記錄</h2></div>
        ${data.runs.length === 0
            ? '<p style="color:var(--text-muted);text-align:center;padding:0.5rem 0">尚無路線記錄</p>'
            : `<div class="table-wrap"><table><thead><tr>
                <th>機器人</th><th>停靠站數</th><th>狀態</th><th>開始時間</th><th>結束時間</th><th>操作</th>
            </tr></thead><tbody>${data.runs.map(r => `<tr>
                <td>${robotName(r.robot_id)}</td>
                <td>${(r.stops || []).length}</td>
                <td style="color:${STATUS_COLORS[r.status] || 'var(--text-muted)'}">${STATUS_LABELS[r.status] || r.status}</td>
                <td style="color:var(--text-muted);font-size:0.82rem">${fmtTime(r.started_at)}</td>
                <td style="color:var(--text-muted);font-size:0.82rem">${fmtTime(r.completed_at)}</td>
                <td><button class="btn btn-sm btn-primary hist-detail" data-id="${r.id}">詳情</button></td>
            </tr>`).join('')}</tbody></table></div>`}
        ${data.total > data.per_page ? `<div style="margin-top:1rem;display:flex;gap:0.5rem;justify-content:center">
            ${_historyPage > 1 ? '<button class="btn btn-sm btn-primary" id="hist-prev">上一頁</button>' : ''}
            <span style="padding:0.3rem 0.6rem;color:var(--text-muted);font-size:0.82rem">${_historyPage} / ${totalPages}</span>
            ${_historyPage < totalPages ? '<button class="btn btn-sm btn-primary" id="hist-next">下一頁</button>' : ''}
        </div>` : ''}
    </div>`;

    section.querySelector('#hist-prev')?.addEventListener('click', () => renderHistory(_historyPage - 1));
    section.querySelector('#hist-next')?.addEventListener('click', () => renderHistory(_historyPage + 1));

    section.querySelectorAll('.hist-detail').forEach(btn => {
        btn.onclick = async () => {
            try {
                const detail = await api.getRunDetail(btn.dataset.id);
                showRunDetailModal(detail);
            } catch (e) { showToast(e.message, 'error'); }
        };
    });
}

function showRunDetailModal(detail) {
    const stops = detail.stops || [];
    const logs = detail.stop_logs || [];

    const bodyHtml = `
        <div style="margin-bottom:0.75rem">
            <span style="color:var(--text-muted);font-size:0.82rem">機器人:</span> <strong>${robotName(detail.robot_id)}</strong>
            &nbsp;&nbsp;
            <span style="color:var(--text-muted);font-size:0.82rem">狀態:</span>
            <span style="color:${STATUS_COLORS[detail.status] || 'var(--text-muted)'}">${STATUS_LABELS[detail.status] || detail.status}</span>
        </div>
        <div class="table-wrap"><table><thead><tr>
            <th>#</th><th>位置</th><th>到達</th><th>確認</th><th>離開</th><th>超時</th>
        </tr></thead><tbody>${logs.length > 0 ? logs.map(l => `<tr>
            <td>${l.stop_index + 1}</td>
            <td>${l.location_name}</td>
            <td style="font-size:0.78rem;color:var(--text-muted)">${fmtShortTime(l.arrived_at)}</td>
            <td style="font-size:0.78rem;color:var(--text-muted)">${l.confirmed_at ? fmtShortTime(l.confirmed_at) + (l.confirmed_by ? ' (' + l.confirmed_by + ')' : '') : '--'}</td>
            <td style="font-size:0.78rem;color:var(--text-muted)">${fmtShortTime(l.departed_at)}</td>
            <td style="color:${l.timed_out ? 'var(--warning)' : 'var(--success)'}">${l.timed_out ? '是' : '否'}</td>
        </tr>`).join('') : `<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">尚無停靠記錄</td></tr>`}</tbody></table></div>
        <div style="margin-top:0.75rem;font-size:0.82rem;color:var(--text-muted)">
            開始: ${fmtTime(detail.started_at)} &nbsp; 結束: ${fmtTime(detail.completed_at)}
        </div>`;

    showModal('路線詳情', bodyHtml, (ol) => { ol.remove(); });
}
