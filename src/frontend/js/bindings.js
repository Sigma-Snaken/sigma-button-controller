import { api } from './api.js';
import { showToast } from './app.js';

const container = document.getElementById('bindings');
const TRIGGERS = ['single','double','long'];
const TRIGGER_LABELS = {single:'單擊',double:'雙擊',long:'長按'};
const ACTIONS = [
    {value:'move_to_location',label:'移動到位置'},{value:'return_home',label:'回充電座'},{value:'speak',label:'語音播報'},
    {value:'move_shelf',label:'搬運貨架'},{value:'return_shelf',label:'歸還貨架'},{value:'dock_shelf',label:'對接貨架'},
    {value:'undock_shelf',label:'放下貨架'},{value:'start_shortcut',label:'執行捷徑'},
];

export async function initBindings() { await renderBindings(); }

async function renderBindings() {
    const buttons = await api.listButtons();
    const robots = await api.listRobots();
    container.innerHTML = `<div class="card"><div class="card-header"><h2>動作設定</h2></div>${buttons.length===0?'<p style="color:var(--text-muted)">請先配對按鈕</p>':`<div class="form-group"><label>選擇按鈕</label><select id="bind-button-select">${buttons.map(b=>`<option value="${b.id}">${b.name||b.ieee_addr}</option>`).join('')}</select></div><div id="trigger-slots"></div><div style="margin-top:1rem;text-align:right"><button class="btn btn-primary" id="save-bindings">儲存設定</button></div>`}</div>`;
    if(buttons.length===0) return;
    const sel=container.querySelector('#bind-button-select');
    sel.onchange=()=>loadBindings(sel.value,robots);
    await loadBindings(sel.value,robots);
    container.querySelector('#save-bindings').onclick=()=>saveBindings(sel.value);
}

async function loadBindings(buttonId,robots) {
    const data = await api.getBindings(buttonId);
    const slotsDiv = container.querySelector('#trigger-slots');
    slotsDiv.innerHTML = `<div class="trigger-grid">${TRIGGERS.map(t=>{const b=data.bindings[t];return `<div class="trigger-slot" data-trigger="${t}"><h4>${TRIGGER_LABELS[t]}</h4><div class="form-group"><label>機器人</label><select class="bind-robot"><option value="">-- 不設定 --</option>${robots.map(r=>`<option value="${r.id}" ${b&&b.robot_id===r.id?'selected':''}>${r.name}</option>`).join('')}</select></div><div class="form-group"><label>動作</label><select class="bind-action"><option value="">-- 選擇動作 --</option>${ACTIONS.map(a=>`<option value="${a.value}" ${b&&b.action===a.value?'selected':''}>${a.label}</option>`).join('')}</select></div><div class="bind-params"></div></div>`;}).join('')}</div>`;
    slotsDiv.querySelectorAll('.trigger-slot').forEach(slot=>{
        const trigger=slot.dataset.trigger;const b=data.bindings[trigger];
        const actionSel=slot.querySelector('.bind-action'),robotSel=slot.querySelector('.bind-robot'),paramsDiv=slot.querySelector('.bind-params');
        const renderParams=async()=>{
            const action=actionSel.value,robotId=robotSel.value;
            paramsDiv.innerHTML='';
            if(!action)return;
            if(!robotId&&['move_to_location','move_shelf','return_shelf','start_shortcut'].includes(action)){
                paramsDiv.innerHTML='<p style="color:var(--warning);font-size:0.8rem">請先選擇機器人</p>';return;
            }
            try{
                if(action==='move_to_location'){
                    const d=await api.getLocations(robotId);const locs=d.locations||[];
                    const cur=b&&b.action===action?b.params.name:'';
                    paramsDiv.innerHTML=`<div class="form-group"><label>位置</label><select class="param-name"><option value="">-- 選擇位置 --</option>${locs.map(l=>`<option value="${l.name}" ${l.name===cur?'selected':''}>${l.name}</option>`).join('')}</select></div>`;
                }else if(action==='speak'){
                    const cur=b&&b.action===action?b.params.text:'';
                    paramsDiv.innerHTML=`<div class="form-group"><label>內容</label><input class="param-text" value="${cur}"></div>`;
                }else if(action==='move_shelf'){
                    const [sd,ld]=await Promise.all([api.getShelves(robotId),api.getLocations(robotId)]);
                    const shelves=sd.shelves||[],locs=ld.locations||[];
                    const cs=b&&b.action===action?b.params.shelf:'',cl=b&&b.action===action?b.params.location:'';
                    paramsDiv.innerHTML=`<div class="form-group"><label>貨架</label><select class="param-shelf"><option value="">-- 選擇貨架 --</option>${shelves.map(s=>`<option value="${s.name}" ${s.name===cs?'selected':''}>${s.name}</option>`).join('')}</select></div><div class="form-group"><label>目標位置</label><select class="param-location"><option value="">-- 選擇位置 --</option>${locs.map(l=>`<option value="${l.name}" ${l.name===cl?'selected':''}>${l.name}</option>`).join('')}</select></div>`;
                }else if(action==='return_shelf'){
                    const sd=await api.getShelves(robotId);const shelves=sd.shelves||[];
                    const cs=b&&b.action===action?b.params.shelf:'';
                    paramsDiv.innerHTML=`<div class="form-group"><label>貨架</label><select class="param-shelf"><option value="">-- 選擇貨架 --</option>${shelves.map(s=>`<option value="${s.name}" ${s.name===cs?'selected':''}>${s.name}</option>`).join('')}</select></div>`;
                }else if(action==='start_shortcut'){
                    const d=await api.getShortcuts(robotId);const raw=d.shortcuts||{};
                    const scs=Array.isArray(raw)?raw:Object.entries(raw).map(([id,name])=>({id,name}));
                    const cur=b&&b.action===action?b.params.shortcut_id:'';
                    paramsDiv.innerHTML=`<div class="form-group"><label>捷徑</label><select class="param-shortcut_id"><option value="">-- 選擇捷徑 --</option>${scs.map(s=>`<option value="${s.id}" ${s.id===cur?'selected':''}>${s.name||s.id}</option>`).join('')}</select></div>`;
                }
            }catch(e){paramsDiv.innerHTML=`<p style="color:var(--danger);font-size:0.8rem">無法取得資料: ${e.message}</p>`;}
        };
        actionSel.addEventListener('change',renderParams);robotSel.addEventListener('change',renderParams);renderParams();
    });
}

async function saveBindings(buttonId) {
    const payload={};
    let valid = true;
    container.querySelectorAll('.trigger-slot').forEach(slot=>{
        if(!valid) return;
        const trigger=slot.dataset.trigger,robotId=slot.querySelector('.bind-robot').value,action=slot.querySelector('.bind-action').value;
        if(!robotId||!action){payload[trigger]=null;return;}
        let params={};const pd=slot.querySelector('.bind-params');
        if(action==='move_to_location'){
            const v=pd.querySelector('.param-name')?.value;
            if(!v){showToast(`${TRIGGER_LABELS[trigger]}: 請選擇位置`,'error');valid=false;return;}
            params={name:v};
        } else if(action==='speak'){
            const v=pd.querySelector('.param-text')?.value;
            if(!v){showToast(`${TRIGGER_LABELS[trigger]}: 請輸入語音內容`,'error');valid=false;return;}
            params={text:v};
        } else if(action==='move_shelf'){
            const s=pd.querySelector('.param-shelf')?.value, l=pd.querySelector('.param-location')?.value;
            if(!s||!l){showToast(`${TRIGGER_LABELS[trigger]}: 請選擇貨架和位置`,'error');valid=false;return;}
            params={shelf:s,location:l};
        } else if(action==='return_shelf'){
            const s=pd.querySelector('.param-shelf')?.value||'';
            params={shelf:s};
        } else if(action==='start_shortcut'){
            const v=pd.querySelector('.param-shortcut_id')?.value;
            if(!v){showToast(`${TRIGGER_LABELS[trigger]}: 請選擇捷徑`,'error');valid=false;return;}
            params={shortcut_id:v};
        }
        // return_home, dock_shelf, undock_shelf: params stays {}
        payload[trigger]={robot_id:robotId,action,params};
    });
    if(!valid) return;
    try{await api.updateBindings(buttonId,payload);showToast('設定已儲存');}catch(e){showToast(e.message,'error');}
}
