import { ws } from './websocket.js';
import { initRobots } from './robots.js';
import { initButtons } from './buttons.js';
import { initBindings } from './bindings.js';
import { initLogs } from './logs.js';
import { initMonitor } from './monitor.js';

document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(tab.dataset.tab).classList.add('active');
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
