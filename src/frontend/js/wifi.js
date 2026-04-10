import { api } from './api.js';
import { showToast, showModal } from './app.js';

const container = document.getElementById('wifi');

export async function initWifi() {
    await renderWifi();
}

async function renderWifi() {
    container.innerHTML = `<div class="card"><div class="card-header"><h2>WiFi 狀態</h2></div><p class="hint">載入中...</p></div>`;
    const status = await api.getWifiStatus().catch(() => ({
        connected: false, ssid: '', ip: '', signal: 0, mode: 'unknown', error: '無法取得 WiFi 狀態'
    }));

    const isAP = status.mode === 'ap';
    const statusClass = status.connected ? 'online' : 'offline';
    const statusText = isAP ? `AP 模式 (${status.ssid})` :
        status.connected ? `已連線: ${status.ssid}` : '未連線';

    container.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h2>WiFi 狀態</h2>
                <button class="btn btn-sm" id="wifi-refresh">重新整理</button>
            </div>
            <div class="wifi-status">
                <div class="wifi-status-row">
                    <span class="sys-label">狀態</span>
                    <span class="status-dot status-${statusClass}"></span>
                    <span class="sys-value">${statusText}</span>
                </div>
                ${status.ip ? `<div class="wifi-status-row">
                    <span class="sys-label">IP</span>
                    <span class="sys-value">${status.ip}</span>
                </div>` : ''}
                ${status.connected && !isAP ? `<div class="wifi-status-row">
                    <span class="sys-label">訊號</span>
                    <span class="sys-value">${signalBar(status.signal)} ${status.signal}%</span>
                </div>` : ''}
                ${status.error ? `<div class="wifi-status-row">
                    <span class="sys-label">錯誤</span>
                    <span class="sys-value text-danger">${status.error}</span>
                </div>` : ''}
            </div>
        </div>

        <div class="card">
            <div class="card-header">
                <h2>AP 配網模式</h2>
            </div>
            <p class="hint">啟動 AP 後，手機連上此熱點即可透過 Web UI 設定新的 WiFi。</p>
            <div class="hotspot-controls">
                ${isAP ? `
                    <div class="hotspot-info">
                        <span class="sys-label">SSID</span> <strong>${status.ssid}</strong>
                    </div>
                    <button class="btn btn-danger" id="hotspot-stop">關閉 AP</button>
                ` : `
                    <div class="form-group form-inline">
                        <label>SSID</label>
                        <input id="ap-ssid" value="SIGMA-SETUP" />
                    </div>
                    <div class="form-group form-inline">
                        <label>密碼</label>
                        <input id="ap-pass" value="" type="password" placeholder="至少 8 碼" disabled />
                        <label style="white-space:nowrap"><input type="checkbox" id="ap-open" checked style="margin-right:4px;vertical-align:middle"> 開放</label>
                    </div>
                    <button class="btn btn-primary" id="hotspot-start">啟動 AP</button>
                `}
            </div>
        </div>

        <div class="card">
            <div class="card-header">
                <h2>可用網路</h2>
                <button class="btn btn-sm btn-primary" id="wifi-scan">掃描</button>
            </div>
            <div id="wifi-networks">
                <p class="hint">點擊「掃描」搜尋附近的 WiFi 網路</p>
            </div>
        </div>
    `;

    container.querySelector('#wifi-refresh').onclick = () => renderWifi();
    container.querySelector('#wifi-scan').onclick = scanNetworks;

    if (isAP) {
        container.querySelector('#hotspot-stop').onclick = stopHotspot;
    } else {
        const openCb = container.querySelector('#ap-open');
        const passInput = container.querySelector('#ap-pass');
        openCb.onchange = () => { passInput.disabled = openCb.checked; if (openCb.checked) passInput.value = ''; };
        container.querySelector('#hotspot-start').onclick = startHotspot;
    }
}

function signalBar(strength) {
    if (strength >= 75) return '▂▄▆█';
    if (strength >= 50) return '▂▄▆░';
    if (strength >= 25) return '▂▄░░';
    return '▂░░░';
}

async function scanNetworks() {
    const list = container.querySelector('#wifi-networks');
    list.innerHTML = '<p class="hint">掃描中...</p>';

    try {
        const result = await api.scanWifi();
        if (result.error) {
            list.innerHTML = `<p class="hint text-danger">${result.error}</p>`;
            return;
        }
        if (!result.networks.length) {
            list.innerHTML = '<p class="hint">未找到任何網路</p>';
            return;
        }
        list.innerHTML = `<table><thead><tr>
            <th>SSID</th><th>訊號</th><th>加密</th><th>操作</th>
        </tr></thead><tbody>${result.networks.map(n => `
            <tr>
                <td>${n.in_use ? '✓ ' : ''}${n.ssid}</td>
                <td>${signalBar(n.signal)} ${n.signal}%</td>
                <td>${n.security}</td>
                <td>${n.in_use ? '<span class="text-success">已連線</span>' :
                    `<button class="btn btn-sm btn-primary wifi-connect-btn" data-ssid="${n.ssid}" data-security="${n.security}">連線</button>`
                }</td>
            </tr>
        `).join('')}</tbody></table>`;

        list.querySelectorAll('.wifi-connect-btn').forEach(btn => {
            btn.onclick = () => connectToNetwork(btn.dataset.ssid, btn.dataset.security);
        });
    } catch (e) {
        list.innerHTML = `<p class="hint text-danger">${e.message}</p>`;
    }
}

function connectToNetwork(ssid, security) {
    const needPassword = security !== 'Open';
    if (needPassword) {
        showModal(`連線至 ${ssid}`, `<div class="form-group"><label>密碼</label><input id="wifi-pwd" type="password" placeholder="輸入 WiFi 密碼"></div>`, async () => {
            const password = document.getElementById('wifi-pwd').value;
            await doConnect(ssid, password);
        });
    } else {
        doConnect(ssid, '');
    }
}

async function doConnect(ssid, password) {
    try {
        const result = await api.connectWifi({ ssid, password });
        if (result.ok) {
            showToast(result.message);
            setTimeout(() => renderWifi(), 5000);
        } else {
            showToast(result.error, 'error');
        }
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function startHotspot() {
    const ssid = container.querySelector('#ap-ssid').value.trim();
    const isOpen = container.querySelector('#ap-open').checked;
    const password = isOpen ? '' : container.querySelector('#ap-pass').value.trim();
    if (!isOpen && password.length < 8) {
        showToast('密碼至少 8 碼', 'error');
        return;
    }
    try {
        const result = await api.startHotspot({ ssid, password });
        if (result.ok) {
            showToast(result.message);
            setTimeout(() => renderWifi(), 3000);
        } else {
            showToast(result.error, 'error');
        }
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function stopHotspot() {
    try {
        const result = await api.stopHotspot();
        if (result.ok) {
            showToast(result.message);
            setTimeout(() => renderWifi(), 3000);
        } else {
            showToast(result.error, 'error');
        }
    } catch (e) {
        showToast(e.message, 'error');
    }
}
