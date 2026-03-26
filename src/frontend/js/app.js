import { ws } from './websocket.js';
import { initRobots } from './robots.js';
import { initButtons } from './buttons.js';
import { initBindings } from './bindings.js';
import { initLogs } from './logs.js';
import { initMonitor } from './monitor.js';

const TAB_LABELS = {
    robots: '機器人',
    buttons: '按鈕',
    bindings: '綁定設定',
    logs: '執行記錄',
    monitor: '機器人監控',
};

function switchTab(tabId) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    const tab = document.querySelector(`.tab[data-tab="${tabId}"]`);
    if (tab) tab.classList.add('active');
    document.getElementById(tabId)?.classList.add('active');
    // Update FAB panel active state
    document.querySelectorAll('.fab-item').forEach(item => {
        item.classList.toggle('active', item.dataset.tab === tabId);
    });
}

// Desktop tabs
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
});

// FAB menu (mobile)
const fabBtn = document.getElementById('fab-menu');
const fabPanel = document.getElementById('fab-panel');
const fabOverlay = document.getElementById('fab-overlay');

// Populate FAB panel
fabPanel.innerHTML = Object.entries(TAB_LABELS).map(([id, label]) =>
    `<button class="fab-item ${id === 'robots' ? 'active' : ''}" data-tab="${id}">${label}</button>`
).join('');

function toggleFab() {
    const isOpen = !fabPanel.classList.contains('hidden');
    fabPanel.classList.toggle('hidden', isOpen);
    fabOverlay.classList.toggle('hidden', isOpen);
    fabBtn.textContent = isOpen ? '\u2630' : '\u2715';
}

fabBtn.addEventListener('click', toggleFab);
fabOverlay.addEventListener('click', toggleFab);

fabPanel.querySelectorAll('.fab-item').forEach(item => {
    item.addEventListener('click', () => {
        switchTab(item.dataset.tab);
        toggleFab();
    });
});

export function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type}`;
    setTimeout(() => toast.classList.add('hidden'), 3000);
}

export function showModal(title, bodyHtml, onConfirm) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `<div class="modal"><h3>${title}</h3><div>${bodyHtml}</div><div class="modal-actions"><button class="btn btn-danger" id="modal-cancel">取消</button><button class="btn btn-primary" id="modal-confirm">確認</button></div></div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('#modal-cancel').onclick = () => overlay.remove();
    overlay.querySelector('#modal-confirm').onclick = () => { onConfirm(overlay); overlay.remove(); };
    return overlay;
}

ws.connect();
initRobots();
initButtons(ws);
initBindings();
initLogs(ws);
initMonitor();
