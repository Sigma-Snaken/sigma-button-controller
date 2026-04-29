import { api } from './api.js';
import { showToast, showModal } from './app.js';

const container = document.getElementById('robots');
const AL = {
    move_to_location: '移動', return_home: '回家', speak: '語音',
    move_shelf: '搬貨架', return_shelf: '還貨架', dock_shelf: '對接',
    undock_shelf: '放下', reset_shelf: '重置位置', start_shortcut: '捷徑', cancel_command: '取消命令',
};

export async function initRobots(ws) {
    ws.on('queue:added', () => renderQueue());
    ws.on('queue:executing', () => renderQueue());
    ws.on('queue:completed', () => renderQueue());
    ws.on('queue:removed', () => renderQueue());
    ws.on('queue:cancelled', () => renderQueue());
    ws.on('robot:connection', () => renderRobots());
    await renderRobots();
}

function fmtBattery(b) {
    if (b == null) return '—';
    return Math.round(b) + '%';
}

function fmtAction(action, params) {
    const label = AL[action] || action;
    if (action === 'move_to_location') return label + ' → ' + (params.name || '');
    if (action === 'speak') return label + ' → "' + (params.text || '') + '"';
    if (action === 'move_shelf') return label + ' → ' + (params.shelf || '') + ' → ' + (params.location || '');
    if (action === 'return_shelf') return label + (params.shelf ? ' → ' + params.shelf : '');
    if (action === 'reset_shelf') return label + ' → ' + (params.shelf || '');
    if (action === 'start_shortcut') return label + ' → ' + (params.shortcut_id || '');
    return label;
}

function renderSkeleton() {
    container.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h2>已註冊機器人</h2>
                <button class="btn btn-primary" id="add-robot">+ 新增機器人</button>
            </div>
            <div class="table-wrap">
                <table><thead><tr>
                    <th>名稱</th><th>IP</th><th>序號</th><th>狀態</th><th>電量</th><th>操作</th>
                </tr></thead><tbody id="robots-body">
                    <tr><td colspan="6" style="text-align:center;color:var(--text-muted)">載入中...</td></tr>
                </tbody></table>
            </div>
        </div>
        <div id="queue-section"></div>`;
    container.querySelector('#add-robot').onclick = () => {
        showModal('新增機器人', '<div class="form-group"><label>名稱</label><input id="r-name" placeholder="大廳機器人"></div><div class="form-group"><label>IP</label><input id="r-ip" placeholder="192.168.50.101"></div>', async () => {
            try { await api.createRobot({name:document.getElementById('r-name').value,ip:document.getElementById('r-ip').value}); showToast('機器人已新增'); await renderRobots(); } catch(e) { showToast(e.message,'error'); }
        });
    };
}

function fillRobots(robots) {
    const tbody = container.querySelector('#robots-body');
    tbody.innerHTML = robots.map(r => `<tr>
        <td>${r.name}</td>
        <td style="color:var(--text-muted)">${r.ip}</td>
        <td style="color:var(--text-muted);font-size:0.78rem">${r.serial||'—'}</td>
        <td><span class="status-dot ${r.online?'status-online':'status-offline'}"></span>${r.online?'在線':'離線'}</td>
        <td>${fmtBattery(r.battery)}</td>
        <td><button class="btn btn-sm btn-primary edit-robot" data-id="${r.id}" data-name="${r.name}" data-ip="${r.ip}">編輯</button> <button class="btn btn-sm btn-danger del-robot" data-id="${r.id}">刪除</button></td>
    </tr>`).join('') || '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">尚無機器人</td></tr>';
    bindActions();
}

function bindActions() {
    container.querySelectorAll('.edit-robot').forEach(btn => {
        btn.onclick = () => { const {id,name,ip} = btn.dataset; showModal('編輯機器人', `<div class="form-group"><label>名稱</label><input id="r-name" value="${name}"></div><div class="form-group"><label>IP</label><input id="r-ip" value="${ip}"></div>`, async () => { try { await api.updateRobot(id,{name:document.getElementById('r-name').value,ip:document.getElementById('r-ip').value}); showToast('已更新'); await renderRobots(); } catch(e) { showToast(e.message,'error'); } }); };
    });
    container.querySelectorAll('.del-robot').forEach(btn => {
        btn.onclick = async () => { if(confirm('確定刪除？')){ await api.deleteRobot(btn.dataset.id); showToast('已刪除'); await renderRobots(); } };
    });
}

async function renderRobots() {
    renderSkeleton();
    const robots = await api.listRobots();
    fillRobots(robots);
    await renderQueue();
}

async function renderQueue() {
    const section = container.querySelector('#queue-section');
    if (!section) return;

    let data;
    try {
        data = await api.getQueue();
    } catch {
        section.innerHTML = '';
        return;
    }

    const { items, enabled } = data;

    // Group by robot_id
    const grouped = {};
    for (const item of items) {
        if (!grouped[item.robot_id]) grouped[item.robot_id] = [];
        grouped[item.robot_id].push(item);
    }

    const toggleChecked = enabled ? 'checked' : '';
    let html = `<div class="card">
        <div class="card-header">
            <h2>命令佇列</h2>
            <label style="display:flex;align-items:center;gap:0.5rem;font-size:0.85rem;cursor:pointer">
                <input type="checkbox" id="queue-toggle" ${toggleChecked}>
                <span>${enabled ? '已啟用' : '已停用'}</span>
            </label>
        </div>`;

    const robotIds = Object.keys(grouped);
    if (robotIds.length === 0) {
        html += `<p style="color:var(--text-muted);text-align:center;padding:1rem 0">佇列為空</p>`;
    } else {
        for (const robotId of robotIds) {
            const robotItems = grouped[robotId];
            html += `<div style="margin-bottom:1rem">
                <h4 style="margin:0.75rem 0 0.5rem;color:var(--text-secondary)">${robotId}</h4>
                <div class="table-wrap"><table><thead><tr>
                    <th>狀態</th><th>動作</th><th>排隊時間</th><th>操作</th>
                </tr></thead><tbody>`;
            for (const item of robotItems) {
                const isExecuting = item.status === 'executing';
                const statusLabel = isExecuting ? '● 執行中' : '○ 等待中';
                const statusColor = isExecuting ? 'var(--success)' : 'var(--text-muted)';
                const time = item.enqueued_at ? new Date(item.enqueued_at).toLocaleTimeString('zh-TW') : '—';
                const actionBtn = isExecuting
                    ? `<button class="btn btn-sm btn-danger cancel-cmd" data-robot="${robotId}">取消</button>`
                    : `<button class="btn btn-sm btn-danger remove-queue" data-id="${item.id}">刪除</button>`;
                html += `<tr>
                    <td style="color:${statusColor}">${statusLabel}</td>
                    <td>${fmtAction(item.action, item.params)}</td>
                    <td style="color:var(--text-muted);font-size:0.82rem">${time}</td>
                    <td>${actionBtn}</td>
                </tr>`;
            }
            html += `</tbody></table></div></div>`;
        }
    }
    html += `</div>`;
    section.innerHTML = html;

    // Bind toggle
    section.querySelector('#queue-toggle')?.addEventListener('change', async (e) => {
        try {
            await api.updateQueueSettings({ enabled: e.target.checked });
            showToast(e.target.checked ? '佇列已啟用' : '佇列已停用');
            await renderQueue();
        } catch (err) { showToast(err.message, 'error'); }
    });

    // Bind cancel buttons
    section.querySelectorAll('.cancel-cmd').forEach(btn => {
        btn.onclick = async () => {
            try {
                await api.cancelCurrent(btn.dataset.robot);
                showToast('已取消');
                await renderQueue();
            } catch (err) { showToast(err.message, 'error'); }
        };
    });

    // Bind remove buttons
    section.querySelectorAll('.remove-queue').forEach(btn => {
        btn.onclick = async () => {
            try {
                await api.removeFromQueue(btn.dataset.id);
                showToast('已移除');
                await renderQueue();
            } catch (err) { showToast(err.message, 'error'); }
        };
    });
}
