import { api } from './api.js';
import { ws } from './websocket.js';
import { initRobots } from './robots.js';
import { initRoutes } from './routes.js';
import { initButtons } from './buttons.js';
import { initBindings } from './bindings.js';
import { initLogs } from './logs.js';
import { initMonitor } from './monitor.js';
import { initWifi } from './wifi.js';

const TAB_LABELS = {
    robots: '機器人',
    routes: '路線',
    buttons: '按鈕',
    bindings: '動作設定',
    logs: '執行記錄',
    monitor: '機器人監控',
    wifi: 'WiFi 設定',
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

// MQTT broker connectivity banner — fires on broker stop/start
ws.on('mqtt:state', (data) => {
    if (data.connected) {
        showToast('MQTT 連線恢復', 'success');
    } else {
        showToast('MQTT 中斷 — 按鈕暫時無法觸發', 'error');
    }
});

// Load system info bar
api.getSystemInfo().then(info => {
    const parts = [];
    if (info.wifi_ip) parts.push(`<span class="sys-label">WiFi</span> <span class="sys-value">${info.wifi_ip}</span>`);
    if (info.eth_ip) parts.push(`<span class="sys-label">LAN</span> <span class="sys-value">${info.eth_ip}</span>`);
    if (!parts.length) parts.push(`<span class="sys-label">URL</span> <span class="sys-value">${info.url}</span>`);
    document.getElementById('system-bar').innerHTML = parts.join('<span style="margin:0 0.5rem;color:var(--border-medium)">|</span>');
}).catch(() => {});

ws.connect();
initRobots(ws);
initRoutes(ws);
initButtons(ws);
initBindings();
initLogs(ws);
initMonitor(ws);
initWifi();
// All init functions render skeletons synchronously then await data independently
