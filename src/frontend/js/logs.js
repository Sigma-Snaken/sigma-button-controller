import { api } from './api.js';

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
    container.innerHTML = `<div class="card"><div class="card-header"><h2>執行記錄</h2></div><div class="table-wrap"><table><thead><tr><th>時間</th><th>按鈕</th><th>動作</th><th>機器人</th><th>結果</th></tr></thead><tbody>${data.logs.map(l=>`<tr><td style="color:var(--text-muted);font-size:0.82rem">${l.executed_at?new Date(l.executed_at).toLocaleString('zh-TW'):'—'}</td><td>${l.button_name||l.button_id}</td><td>${AL[l.action]||l.action}${l.action==='move_to_location'?' → '+(l.params.name||''):l.action==='speak'?' → "'+(l.params.text||'')+'"':''}</td><td style="color:var(--text-muted)">${l.robot_id}</td><td style="color:${l.result_ok?'var(--success)':'var(--coral)'}">${l.result_ok?'✓':'✗ '+parseError(l.result_detail)}</td></tr>`).join('')}${data.logs.length===0?'<tr><td colspan="5" style="text-align:center;color:var(--text-muted)">尚無執行記錄</td></tr>':''}</tbody></table></div>${data.total>data.per_page?`<div style="margin-top:1rem;display:flex;gap:0.5rem;justify-content:center">${page>1?`<button class="btn btn-sm btn-primary" id="prev-page">上一頁</button>`:''}<span style="padding:0.3rem 0.6rem;color:var(--text-muted);font-size:0.82rem">${page} / ${Math.ceil(data.total/data.per_page)}</span>${page*data.per_page<data.total?`<button class="btn btn-sm btn-primary" id="next-page">下一頁</button>`:''}</div>`:''}</div>`;
    container.querySelector('#prev-page')?.addEventListener('click',()=>renderLogs(page-1));
    container.querySelector('#next-page')?.addEventListener('click',()=>renderLogs(page+1));
}
