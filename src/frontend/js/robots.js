import { api } from './api.js';
import { showToast, showModal } from './app.js';

const container = document.getElementById('robots');

export async function initRobots() { await renderRobots(); }

function fmtBattery(b) {
    if (b == null) return '—';
    return Math.round(b) + '%';
}

async function renderRobots() {
    const robots = await api.listRobots();
    container.innerHTML = `<div class="card"><div class="card-header"><h2>已註冊機器人</h2><button class="btn btn-primary" id="add-robot">+ 新增機器人</button></div><table><thead><tr><th>名稱</th><th>IP</th><th>序號</th><th>狀態</th><th>電量</th><th>操作</th></tr></thead><tbody>${robots.map(r => `<tr><td>${r.name}</td><td style="color:var(--text-muted)">${r.ip}</td><td style="color:var(--text-muted);font-size:0.78rem">${r.serial||'—'}</td><td><span class="status-dot ${r.online?'status-online':'status-offline'}"></span>${r.online?'在線':'離線'}</td><td>${fmtBattery(r.battery)}</td><td><button class="btn btn-sm btn-primary edit-robot" data-id="${r.id}" data-name="${r.name}" data-ip="${r.ip}">編輯</button> <button class="btn btn-sm btn-danger del-robot" data-id="${r.id}">刪除</button></td></tr>`).join('')}${robots.length===0?'<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">尚無機器人</td></tr>':''}</tbody></table></div>`;
    container.querySelector('#add-robot').onclick = () => {
        showModal('新增機器人', '<div class="form-group"><label>名稱</label><input id="r-name" placeholder="大廳機器人"></div><div class="form-group"><label>IP</label><input id="r-ip" placeholder="192.168.50.101"></div>', async () => {
            try { await api.createRobot({name:document.getElementById('r-name').value,ip:document.getElementById('r-ip').value}); showToast('機器人已新增'); await renderRobots(); } catch(e) { showToast(e.message,'error'); }
        });
    };
    container.querySelectorAll('.edit-robot').forEach(btn => {
        btn.onclick = () => { const {id,name,ip} = btn.dataset; showModal('編輯機器人', `<div class="form-group"><label>名稱</label><input id="r-name" value="${name}"></div><div class="form-group"><label>IP</label><input id="r-ip" value="${ip}"></div>`, async () => { try { await api.updateRobot(id,{name:document.getElementById('r-name').value,ip:document.getElementById('r-ip').value}); showToast('已更新'); await renderRobots(); } catch(e) { showToast(e.message,'error'); } }); };
    });
    container.querySelectorAll('.del-robot').forEach(btn => {
        btn.onclick = async () => { if(confirm('確定刪除？')){ await api.deleteRobot(btn.dataset.id); showToast('已刪除'); await renderRobots(); } };
    });
}
