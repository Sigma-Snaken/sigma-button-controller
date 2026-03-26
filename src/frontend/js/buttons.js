import { api } from './api.js';
import { showToast } from './app.js';

const container = document.getElementById('buttons');
let pairTimer = null;

export async function initButtons(ws) {
    ws.on('device_paired', async () => { showToast('新設備已配對!'); await renderButtons(); });
    await renderButtons();
}

async function renderButtons() {
    const buttons = await api.listButtons();
    container.innerHTML = `<div class="card"><div class="card-header"><h2>已配對按鈕</h2><button class="btn btn-success" id="start-pair">開始配對</button></div><div class="table-wrap"><table><thead><tr><th>名稱</th><th>IEEE</th><th>電量</th><th>最後回報</th><th>操作</th></tr></thead><tbody>${buttons.map(b => `<tr><td>${b.name||b.ieee_addr}</td><td style="color:var(--text-muted);font-size:0.78rem">${b.ieee_addr}</td><td>${b.battery!=null?b.battery+'%':'—'}</td><td style="color:var(--text-muted);font-size:0.78rem">${b.last_seen?new Date(b.last_seen).toLocaleString('zh-TW',{hour12:false}):'—'}</td><td><button class="btn btn-sm btn-primary rename-btn" data-id="${b.id}" data-name="${b.name||''}">重命名</button> <button class="btn btn-sm btn-danger del-btn" data-id="${b.id}">移除</button></td></tr>`).join('')}${buttons.length===0?'<tr><td colspan="5" style="text-align:center;color:var(--text-muted)">尚無配對按鈕</td></tr>':''}</tbody></table></div></div><div class="pair-zone hidden" id="pair-zone"><h4 style="color:var(--success)">配對模式啟動中...</h4><p style="font-size:0.82rem;color:var(--text-muted);margin-top:0.5rem">請長按 SNZB-01 按鈕 5 秒直到 LED 閃爍</p><p style="margin-top:0.5rem;font-size:0.82rem;color:var(--success)" id="pair-countdown"></p><button class="btn btn-danger" style="margin-top:0.75rem" id="stop-pair">停止配對</button></div>`;
    container.querySelector('#start-pair').onclick = async () => {
        try { await api.startPairing(); const zone=document.getElementById('pair-zone'); zone.classList.remove('hidden'); let rem=120; document.getElementById('pair-countdown').textContent=`等待設備加入... (${rem}s)`; pairTimer=setInterval(()=>{rem--;const el=document.getElementById('pair-countdown');if(el)el.textContent=`等待設備加入... (${rem}s)`;if(rem<=0){clearInterval(pairTimer);zone.classList.add('hidden');}},1000); } catch(e) { showToast(e.message,'error'); }
    };
    const stopBtn=container.querySelector('#stop-pair');
    if(stopBtn) stopBtn.onclick = async () => { clearInterval(pairTimer); await api.stopPairing(); document.getElementById('pair-zone').classList.add('hidden'); };
    container.querySelectorAll('.rename-btn').forEach(btn => { btn.onclick = async () => { const name=prompt('新名稱:',btn.dataset.name); if(name){ await api.updateButton(btn.dataset.id,{name}); showToast('已重命名'); await renderButtons(); } }; });
    container.querySelectorAll('.del-btn').forEach(btn => { btn.onclick = async () => { if(confirm('確定移除？')){ await api.deleteButton(btn.dataset.id); showToast('已移除'); await renderButtons(); } }; });
}
