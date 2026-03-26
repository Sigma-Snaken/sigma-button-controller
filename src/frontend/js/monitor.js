import { api } from './api.js';
import { showToast } from './app.js';

const container = document.getElementById('monitor');
let mapTimer = null;
let frontCamTimer = null;
let backCamTimer = null;
let metricsTimer = null;

const DETECT_LABELS = {0:'未知',1:'人',2:'貨架',3:'充電座',4:'門'};
const DETECT_COLORS = {0:'#ec4899',1:'#22c55e',2:'#3b82f6',3:'#06b6d4',4:'#ef4444'};

export async function initMonitor() {
    await renderMonitor();
}

async function renderMonitor() {
    const robots = await api.listRobots();
    const onlineRobots = robots.filter(r => r.online);

    container.innerHTML = `
        <div class="card">
            <div class="card-header"><h2>機器人監控</h2></div>
            ${onlineRobots.length === 0 ? '<p style="color:var(--text-muted)">無在線機器人</p>' : `
            <div class="form-group">
                <label>選擇機器人</label>
                <select id="monitor-robot-select">
                    ${onlineRobots.map(r => `<option value="${r.id}">${r.name} (${r.ip})</option>`).join('')}
                </select>
            </div>
            <div id="monitor-content">
                <div id="map-section" class="monitor-section">
                    <div class="monitor-section-header">
                        <span class="monitor-label">地圖 / 機器人位置</span>
                        <span id="pose-info" style="font-size:11px;color:var(--text-muted)"></span>
                    </div>
                    <div id="map-container" style="position:relative;display:inline-block;background:var(--panel-dark);border:1px solid var(--border-medium);border-radius:4px;overflow:hidden;">
                        <canvas id="map-canvas"></canvas>
                    </div>
                </div>
                <div class="monitor-cameras">
                    <div class="monitor-section">
                        <div class="monitor-section-header">
                            <span class="monitor-label">前鏡頭</span>
                            <div style="display:flex;gap:0.5rem">
                                <label style="font-size:10px;color:var(--text-muted);display:flex;align-items:center;gap:0.25rem;cursor:pointer">
                                    <input type="checkbox" id="front-detect-toggle"> 物件偵測
                                </label>
                                <button class="btn btn-sm" id="toggle-front-cam">開啟</button>
                            </div>
                        </div>
                        <div id="front-cam-container">
                            <p style="color:var(--text-muted);font-size:11px;padding:1rem;">鏡頭已關閉</p>
                        </div>
                    </div>
                    <div class="monitor-section">
                        <div class="monitor-section-header">
                            <span class="monitor-label">後鏡頭</span>
                            <div style="display:flex;gap:0.5rem">
                                <label style="font-size:10px;color:var(--text-muted);display:flex;align-items:center;gap:0.25rem;cursor:pointer">
                                    <input type="checkbox" id="back-detect-toggle"> 物件偵測
                                </label>
                                <button class="btn btn-sm" id="toggle-back-cam">開啟</button>
                            </div>
                        </div>
                        <div id="back-cam-container">
                            <p style="color:var(--text-muted);font-size:11px;padding:1rem;">鏡頭已關閉</p>
                        </div>
                    </div>
                </div>
                <div class="monitor-section" style="margin-top:1rem">
                    <div class="monitor-section-header">
                        <span class="monitor-label">即時偵測 / 效能指標</span>
                    </div>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem" id="metrics-panel">
                        <div id="detection-panel" style="background:var(--panel-mid);border:1px solid var(--border-subtle);border-radius:4px;padding:0.75rem">
                            <div style="font-size:10px;color:var(--amber-dim);text-transform:uppercase;letter-spacing:1px;margin-bottom:0.5rem">物件偵測</div>
                            <div id="detection-list" style="font-size:11px;color:var(--text-muted)">尚未啟動</div>
                        </div>
                        <div id="perf-panel" style="background:var(--panel-mid);border:1px solid var(--border-subtle);border-radius:4px;padding:0.75rem">
                            <div style="font-size:10px;color:var(--amber-dim);text-transform:uppercase;letter-spacing:1px;margin-bottom:0.5rem">效能指標</div>
                            <div id="perf-list" style="font-size:11px;color:var(--text-muted)">載入中...</div>
                        </div>
                    </div>
                </div>
            </div>
            `}
        </div>
    `;

    if (onlineRobots.length === 0) return;

    const sel = container.querySelector('#monitor-robot-select');
    sel.addEventListener('change', () => {
        stopAllStreams();
        loadMap(sel.value);
        loadMetrics(sel.value);
        resetCamButtons();
    });

    container.querySelector('#toggle-front-cam').addEventListener('click', (e) => {
        const detect = document.getElementById('front-detect-toggle').checked;
        toggleCamera(sel.value, 'front', e.target, detect);
    });
    container.querySelector('#toggle-back-cam').addEventListener('click', (e) => {
        const detect = document.getElementById('back-detect-toggle').checked;
        toggleCamera(sel.value, 'back', e.target, detect);
    });

    loadMap(sel.value);
    loadMetrics(sel.value);
}

async function loadMap(robotId) {
    if (mapTimer) { clearInterval(mapTimer); mapTimer = null; }
    const draw = async () => {
        try {
            const data = await api.getMap(robotId);
            if (!data.ok) return;
            drawMap(data.map, data.pose);
        } catch (e) { console.error('Map load error:', e); }
    };
    await draw();
    mapTimer = setInterval(draw, 3000);
}

function drawMap(map, pose) {
    const canvas = document.getElementById('map-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const img = new Image();
    img.onload = () => {
        const section = document.getElementById('map-section');
        const maxW = Math.min((section ? section.clientWidth - 4 : 500), 500);
        const scale = Math.min(maxW / img.width, 400 / img.height, 1);
        canvas.width = img.width * scale;
        canvas.height = img.height * scale;
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        if (pose) {
            const res = map.resolution || 0.025;
            const ox = map.origin_x || 0;
            const oy = map.origin_y || 0;
            const mapH = map.height || img.height;
            const px = ((pose.x - ox) / res) * scale;
            const py = ((mapH - (pose.y - oy) / res)) * scale;
            ctx.beginPath();
            ctx.arc(px, py, 8, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(220, 53, 69, 0.8)';
            ctx.fill();
            ctx.strokeStyle = 'white';
            ctx.lineWidth = 2;
            ctx.stroke();
            const arrowLen = 16;
            const angle = -pose.theta;
            const ax = px + Math.cos(angle) * arrowLen;
            const ay = py - Math.sin(angle) * arrowLen;
            ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(ax, ay);
            ctx.strokeStyle = 'rgba(220, 53, 69, 0.9)'; ctx.lineWidth = 3; ctx.stroke();
            const headLen = 6;
            ctx.beginPath();
            ctx.moveTo(ax, ay); ctx.lineTo(ax + Math.cos(angle + Math.PI * 0.8) * headLen, ay - Math.sin(angle + Math.PI * 0.8) * headLen);
            ctx.moveTo(ax, ay); ctx.lineTo(ax + Math.cos(angle - Math.PI * 0.8) * headLen, ay - Math.sin(angle - Math.PI * 0.8) * headLen);
            ctx.stroke();
            const info = document.getElementById('pose-info');
            if (info) info.textContent = `x: ${pose.x.toFixed(2)}, y: ${pose.y.toFixed(2)}, θ: ${(pose.theta * 180 / Math.PI).toFixed(1)}°`;
        }
    };
    img.src = `data:image/${map.format || 'png'};base64,${map.image_base64}`;
}

function toggleCamera(robotId, camera, btn, detect) {
    const containerId = camera === 'front' ? 'front-cam-container' : 'back-cam-container';
    const camContainer = document.getElementById(containerId);

    if (btn.textContent === '開啟') {
        btn.textContent = '關閉';
        btn.classList.add('btn-danger');
        btn.classList.remove('btn-success');
        // Start streamer on backend if detect enabled
        if (detect) {
            api.startStreamer(robotId, camera, true).catch(() => {});
        }
        startCameraStream(robotId, camera, camContainer, detect);
    } else {
        btn.textContent = '開啟';
        btn.classList.remove('btn-danger');
        btn.classList.add('btn-success');
        stopCameraStream(camera);
        api.stopStreamer(robotId, camera).catch(() => {});
        camContainer.innerHTML = '<p style="color:var(--text-muted);font-size:11px;padding:1rem;">鏡頭已關閉</p>';
        updateDetectionPanel([]);
    }
}

function startCameraStream(robotId, camera, camContainer, detect) {
    camContainer.innerHTML = `
        <img id="${camera}-cam-img" style="width:100%;max-width:400px;border-radius:4px;display:block;" />
        <p style="color:var(--text-muted);font-size:10px;margin-top:0.25rem" id="${camera}-cam-status">載入中...</p>
    `;

    const fetchFrame = async () => {
        try {
            const data = await api.getCamera(robotId, camera, detect);
            if (data.ok) {
                const img = document.getElementById(camera + '-cam-img');
                if (img) img.src = `data:image/${data.format};base64,${data.image_base64}`;
                const status = document.getElementById(camera + '-cam-status');
                if (status) {
                    let text = new Date().toLocaleTimeString('zh-TW', { hour12: false });
                    if (data.objects && data.objects.length > 0) {
                        text += ` | 偵測到 ${data.objects.length} 個物件`;
                    }
                    status.textContent = text;
                }
                if (detect && data.objects) {
                    updateDetectionPanel(data.objects);
                }
            }
        } catch (e) {
            const status = document.getElementById(camera + '-cam-status');
            if (status) status.textContent = '錯誤: ' + e.message;
        }
    };

    fetchFrame();
    if (camera === 'front') {
        frontCamTimer = setInterval(fetchFrame, 2000);
    } else {
        backCamTimer = setInterval(fetchFrame, 2000);
    }
}

function updateDetectionPanel(objects) {
    const panel = document.getElementById('detection-list');
    if (!panel) return;
    if (!objects || objects.length === 0) {
        panel.innerHTML = '<span style="color:var(--text-ghost)">未偵測到物件</span>';
        return;
    }
    panel.innerHTML = objects.map(obj => {
        const label = DETECT_LABELS[obj.label_id] || obj.label || '未知';
        const color = DETECT_COLORS[obj.label_id] || '#888';
        const score = obj.score != null ? (obj.score * 100).toFixed(0) + '%' : '';
        const dist = obj.distance != null ? obj.distance.toFixed(1) + 'm' : '';
        return `<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.25rem">
            <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${color}"></span>
            <span style="color:var(--text-primary)">${label}</span>
            ${score ? `<span style="color:var(--text-muted)">${score}</span>` : ''}
            ${dist ? `<span style="color:var(--text-muted)">${dist}</span>` : ''}
        </div>`;
    }).join('');
}

async function loadMetrics(robotId) {
    if (metricsTimer) { clearInterval(metricsTimer); metricsTimer = null; }
    const update = async () => {
        try {
            const data = await api.getMetrics(robotId);
            if (!data.ok) return;
            const panel = document.getElementById('perf-list');
            if (!panel) return;
            let html = '';
            // Controller metrics
            if (data.controller) {
                html += `<div style="margin-bottom:0.5rem">
                    <div style="color:var(--text-primary)">RobotController</div>
                    <div>輪詢次數: ${data.controller.poll_count}</div>
                    <div>平均 RTT: ${data.controller.avg_rtt_ms}ms</div>
                    <div>最大 RTT: ${data.controller.max_rtt_ms}ms</div>
                </div>`;
            }
            // Camera stats
            ['front', 'back'].forEach(cam => {
                const key = cam + '_camera';
                if (data[key]) {
                    const c = data[key];
                    const label = cam === 'front' ? '前鏡頭' : '後鏡頭';
                    if (c.running) {
                        html += `<div style="margin-bottom:0.25rem">
                            <span style="color:var(--text-primary)">${label}</span>:
                            ${c.total_frames || 0} 幀,
                            丟棄 ${c.dropped || 0} (${(c.drop_rate_pct || 0).toFixed(1)}%)
                        </div>`;
                    } else {
                        html += `<div><span style="color:var(--text-primary)">${label}</span>: 未啟動</div>`;
                    }
                }
            });
            panel.innerHTML = html || '<span style="color:var(--text-ghost)">無資料</span>';
        } catch (e) {
            console.error('Metrics error:', e);
        }
    };
    await update();
    metricsTimer = setInterval(update, 5000);
}

function stopCameraStream(camera) {
    if (camera === 'front' && frontCamTimer) { clearInterval(frontCamTimer); frontCamTimer = null; }
    if (camera === 'back' && backCamTimer) { clearInterval(backCamTimer); backCamTimer = null; }
}

function stopAllStreams() {
    if (mapTimer) { clearInterval(mapTimer); mapTimer = null; }
    if (frontCamTimer) { clearInterval(frontCamTimer); frontCamTimer = null; }
    if (backCamTimer) { clearInterval(backCamTimer); backCamTimer = null; }
    if (metricsTimer) { clearInterval(metricsTimer); metricsTimer = null; }
}

function resetCamButtons() {
    ['toggle-front-cam', 'toggle-back-cam'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) { btn.textContent = '開啟'; btn.classList.remove('btn-danger'); btn.classList.add('btn-success'); }
    });
    ['front-detect-toggle', 'back-detect-toggle'].forEach(id => {
        const cb = document.getElementById(id);
        if (cb) cb.checked = false;
    });
    document.getElementById('front-cam-container').innerHTML = '<p style="color:var(--text-muted);font-size:11px;padding:1rem;">鏡頭已關閉</p>';
    document.getElementById('back-cam-container').innerHTML = '<p style="color:var(--text-muted);font-size:11px;padding:1rem;">鏡頭已關閉</p>';
    updateDetectionPanel([]);
}
