import { api } from './api.js';
import { showToast } from './app.js';

const container = document.getElementById('logs');
const AL={move_to_location:'移動',return_home:'回家',speak:'語音',move_shelf:'搬貨架',return_shelf:'還貨架',dock_shelf:'對接',undock_shelf:'放下',start_shortcut:'捷徑'};

function parseError(detail) {
    if (!detail) return '';
    try {
        const d = typeof detail === 'string' ? JSON.parse(detail) : detail;
        if (d.error_code) {
            const msg = (d.error || '').replace(/^error_code=\d+:\s*/, '');
            return `[${d.error_code}] ${msg}`;
        }
        if (d.error) return d.error;
        return '';
    } catch { return String(detail); }
}

export async function initLogs(ws) {
    ws.on('action_executed',()=>renderLogs());
    await renderLogs();
}

async function renderLogs(page=1) {
    const data = await api.getLogs(page);
    let notifyConfig = { bot_token: '', chat_id: '', enabled: false };
    try { notifyConfig = await api.getNotifySettings(); } catch {}

    container.innerHTML = `
        <div class="card">
            <div class="card-header"><h2>異常通知設定</h2></div>
            <p style="font-size:11px;color:var(--text-muted);margin-bottom:0.75rem">執行失敗時自動透過 Telegram 發送通知</p>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem">
                <div class="form-group">
                    <label>Telegram Bot Token</label>
                    <input id="notify-bot-token" value="${notifyConfig.bot_token}" placeholder="123456:ABC-DEF...">
                </div>
                <div class="form-group">
                    <label>Chat ID / User ID (多個以逗號分隔)</label>
                    <input id="notify-chat-id" value="${notifyConfig.chat_id}" placeholder="123456789, 987654321">
                </div>
            </div>
            <div style="display:flex;gap:0.5rem;align-items:center">
                <button class="btn btn-primary" id="save-notify">儲存</button>
                <button class="btn btn-sm ${notifyConfig.enabled ? 'btn-success' : ''}" id="test-notify" ${!notifyConfig.enabled ? 'disabled' : ''}>測試通知</button>
                <span style="font-size:10px;color:${notifyConfig.enabled ? 'var(--success)' : 'var(--text-muted)'}" id="notify-status">${notifyConfig.enabled ? '● 已啟用' : '○ 未設定'}</span>
            </div>
        </div>
        <div class="card">
            <div class="card-header"><h2>執行記錄</h2></div>
            <div class="table-wrap"><table><thead><tr><th>時間</th><th>按鈕</th><th>動作</th><th>機器人</th><th>結果</th></tr></thead><tbody>${data.logs.map(l=>`<tr><td style="color:var(--text-muted);font-size:0.82rem">${l.executed_at?new Date(l.executed_at).toLocaleString('zh-TW'):'—'}</td><td>${l.button_name||l.button_id}</td><td>${AL[l.action]||l.action}${l.action==='move_to_location'?' → '+(l.params.name||''):l.action==='speak'?' → "'+(l.params.text||'')+'"':''}</td><td style="color:var(--text-muted)">${l.robot_id}</td><td style="color:${l.result_ok?'var(--success)':'var(--coral)'}">${l.result_ok?'✓':'✗ '+parseError(l.result_detail)}</td></tr>`).join('')}${data.logs.length===0?'<tr><td colspan="5" style="text-align:center;color:var(--text-muted)">尚無執行記錄</td></tr>':''}</tbody></table></div>${data.total>data.per_page?`<div style="margin-top:1rem;display:flex;gap:0.5rem;justify-content:center">${page>1?`<button class="btn btn-sm btn-primary" id="prev-page">上一頁</button>`:''}<span style="padding:0.3rem 0.6rem;color:var(--text-muted);font-size:0.82rem">${page} / ${Math.ceil(data.total/data.per_page)}</span>${page*data.per_page<data.total?`<button class="btn btn-sm btn-primary" id="next-page">下一頁</button>`:''}</div>`:''}</div>`;

    container.querySelector('#save-notify').addEventListener('click', async () => {
        const bot_token = document.getElementById('notify-bot-token').value;
        const chat_id = document.getElementById('notify-chat-id').value;
        try {
            const r = await api.updateNotifySettings({ bot_token, chat_id });
            showToast(r.enabled ? '通知已啟用' : '通知設定已儲存（未啟用）');
            await renderLogs(page);
        } catch (e) { showToast(e.message, 'error'); }
    });

    container.querySelector('#test-notify').addEventListener('click', async () => {
        try {
            const r = await api.testNotify();
            showToast(r.ok ? '測試訊息已發送' : '發送失敗: ' + (r.error || ''), r.ok ? 'success' : 'error');
        } catch (e) { showToast(e.message, 'error'); }
    });

    container.querySelector('#prev-page')?.addEventListener('click',()=>renderLogs(page-1));
    container.querySelector('#next-page')?.addEventListener('click',()=>renderLogs(page+1));
}
