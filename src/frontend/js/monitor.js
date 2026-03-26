import { api } from './api.js';
import { showToast } from './app.js';

const container = document.getElementById('monitor');
let mapTimer = null;
let frontCamTimer = null;
let backCamTimer = null;
let heatmapData = null;
let showHeatmap = false;

// Cached map params for heatmap coordinate conversion
let cachedMapParams = null;

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
                    <div class="monitor-section-header" style="justify-content:center">
                        <span class="monitor-label">地圖 / 機器人位置</span>
                        <span id="pose-info" style="font-size:11px;color:var(--text-muted);margin-left:0.75rem"></span>
                    </div>
                    <div id="map-container" style="position:relative;display:flex;justify-content:center;background:var(--panel-dark);border:1px solid var(--border-medium);border-radius:4px;overflow:hidden;">
                        <canvas id="map-canvas"></canvas>
                    </div>
                    <div style="margin-top:0.75rem;font-size:10px;color:var(--text-muted)">
                        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:0.5rem">
                            <div style="display:flex;align-items:center;gap:0.5rem">
                                <label style="display:flex;align-items:center;gap:0.25rem;cursor:pointer;font-weight:500;color:var(--text-primary)">
                                    <input type="checkbox" id="heatmap-toggle"> 網路效能圖
                                </label>
                                <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#22c55e"></span>&lt;50ms
                                <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#eab308"></span>50-100ms
                                <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#f97316"></span>100-200ms
                                <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#ef4444"></span>&gt;200ms
                            </div>
                            <button class="btn btn-sm btn-danger" id="clear-heatmap">清除資料</button>
                        </div>
                        <div id="heatmap-stats" style="margin-top:0.25rem">0 筆 | 平均 0ms | 最小 0ms | 最大 0ms</div>
                    </div>
                </div>
                <div class="monitor-cameras">
                    <div class="monitor-section">
                        <div class="monitor-section-header">
                            <span class="monitor-label">前鏡頭</span>
                            <button class="btn btn-sm" id="toggle-front-cam">開啟</button>
                        </div>
                        <div id="front-cam-container">
                            <p style="color:var(--text-muted);font-size:11px;padding:1rem;">鏡頭已關閉</p>
                        </div>
                    </div>
                    <div class="monitor-section">
                        <div class="monitor-section-header">
                            <span class="monitor-label">後鏡頭</span>
                            <button class="btn btn-sm" id="toggle-back-cam">開啟</button>
                        </div>
                        <div id="back-cam-container">
                            <p style="color:var(--text-muted);font-size:11px;padding:1rem;">鏡頭已關閉</p>
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
        heatmapData = null;
        loadMap(sel.value);
        resetCamButtons();
    });

    container.querySelector('#toggle-front-cam').addEventListener('click', (e) => toggleCamera(sel.value, 'front', e.target));
    container.querySelector('#toggle-back-cam').addEventListener('click', (e) => toggleCamera(sel.value, 'back', e.target));

    const heatmapToggle = container.querySelector('#heatmap-toggle');
    const clearBtn = container.querySelector('#clear-heatmap');

    // Load stats on init
    api.getRttHeatmap(sel.value).then(data => {
        updateHeatmapStats(data.stats);
    }).catch(() => {});

    heatmapToggle.addEventListener('change', async () => {
        showHeatmap = heatmapToggle.checked;
        if (showHeatmap) {
            heatmapData = await api.getRttHeatmap(sel.value);
            updateHeatmapStats(heatmapData.stats);
        } else {
            heatmapData = null;
        }
    });
    clearBtn.addEventListener('click', async () => {
        if (confirm('確定清除所有網路效能資料？')) {
            await api.clearRttHeatmap(sel.value);
            heatmapData = null;
            updateHeatmapStats({ count: 0, avg_rtt_ms: 0, min_rtt_ms: 0, max_rtt_ms: 0 });
            showToast('網路效能資料已清除');
        }
    });

    loadMap(sel.value);
}

function rttToColor(rtt) {
    if (rtt < 50) return 'rgba(34, 197, 94, 0.5)';   // green
    if (rtt < 100) return 'rgba(234, 179, 8, 0.5)';   // yellow
    if (rtt < 200) return 'rgba(249, 115, 22, 0.5)';  // orange
    return 'rgba(239, 68, 68, 0.5)';                    // red
}

function updateHeatmapStats(stats) {
    const el = document.getElementById('heatmap-stats');
    if (!el || !stats) return;
    el.textContent = `${stats.count} 筆 | 平均 ${stats.avg_rtt_ms}ms | 最小 ${stats.min_rtt_ms}ms | 最大 ${stats.max_rtt_ms}ms`;
}

async function loadMap(robotId) {
    if (mapTimer) { clearInterval(mapTimer); mapTimer = null; }
    const draw = async () => {
        try {
            const data = await api.getMap(robotId);
            if (!data.ok) return;
            // Refresh heatmap periodically if enabled
            if (showHeatmap) {
                heatmapData = await api.getRttHeatmap(robotId);
                updateHeatmapStats(heatmapData.stats);
            }
            drawMap(data.map, data.pose);
        } catch (e) { console.error('Map load error:', e); }
    };
    await draw();
    mapTimer = setInterval(draw, 3000);
}

function worldToPixel(wx, wy, map, scale) {
    const res = map.resolution || 0.025;
    const ox = map.origin_x || 0;
    const oy = map.origin_y || 0;
    const mapH = map.height;
    const px = ((wx - ox) / res) * scale;
    const py = ((mapH - (wy - oy) / res)) * scale;
    return [px, py];
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

        // Cache map params for coordinate conversion
        cachedMapParams = { ...map, scale };

        // Draw RTT heatmap overlay
        if (showHeatmap && heatmapData && heatmapData.points) {
            for (const pt of heatmapData.points) {
                const [px, py] = worldToPixel(pt.x, pt.y, map, scale);
                ctx.beginPath();
                ctx.arc(px, py, 4, 0, Math.PI * 2);
                ctx.fillStyle = rttToColor(pt.rtt_ms);
                ctx.fill();
            }
        }

        // Draw robot position on top
        if (pose) {
            const [px, py] = worldToPixel(pose.x, pose.y, map, scale);

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

async function toggleCamera(robotId, camera, btn) {
    const containerId = camera === 'front' ? 'front-cam-container' : 'back-cam-container';
    const camContainer = document.getElementById(containerId);
    if (btn.textContent === '開啟') {
        btn.textContent = '關閉';
        btn.classList.add('btn-danger');
        btn.classList.remove('btn-success');
        await api.startCamera(robotId, camera);  // Start CameraStreamer on backend
        startCameraStream(robotId, camera, camContainer);
    } else {
        btn.textContent = '開啟';
        btn.classList.remove('btn-danger');
        btn.classList.add('btn-success');
        stopCameraStream(camera);
        await api.stopCamera(robotId, camera);  // Stop CameraStreamer on backend
        camContainer.innerHTML = '<p style="color:var(--text-muted);font-size:11px;padding:1rem;">鏡頭已關閉</p>';
    }
}

function startCameraStream(robotId, camera, camContainer) {
    camContainer.innerHTML = `<img id="${camera}-cam-img" style="width:100%;max-width:400px;border-radius:4px;display:block;" /><p style="color:var(--text-muted);font-size:10px;margin-top:0.25rem" id="${camera}-cam-status">載入中...</p>`;
    const fetchFrame = async () => {
        try {
            const data = await api.getCamera(robotId, camera);
            if (data.ok) {
                const img = document.getElementById(camera + '-cam-img');
                if (img) img.src = `data:image/${data.format};base64,${data.image_base64}`;
                const status = document.getElementById(camera + '-cam-status');
                if (status) status.textContent = new Date().toLocaleTimeString('zh-TW', { hour12: false });
            }
        } catch (e) {
            const status = document.getElementById(camera + '-cam-status');
            if (status) status.textContent = '錯誤: ' + e.message;
        }
    };
    fetchFrame();
    if (camera === 'front') { frontCamTimer = setInterval(fetchFrame, 2000); }
    else { backCamTimer = setInterval(fetchFrame, 2000); }
}

function stopCameraStream(camera) {
    if (camera === 'front' && frontCamTimer) { clearInterval(frontCamTimer); frontCamTimer = null; }
    if (camera === 'back' && backCamTimer) { clearInterval(backCamTimer); backCamTimer = null; }
}

function stopAllStreams() {
    if (mapTimer) { clearInterval(mapTimer); mapTimer = null; }
    if (frontCamTimer) { clearInterval(frontCamTimer); frontCamTimer = null; }
    if (backCamTimer) { clearInterval(backCamTimer); backCamTimer = null; }
}

function resetCamButtons() {
    ['toggle-front-cam', 'toggle-back-cam'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) { btn.textContent = '開啟'; btn.classList.remove('btn-danger'); btn.classList.add('btn-success'); }
    });
    document.getElementById('front-cam-container').innerHTML = '<p style="color:var(--text-muted);font-size:11px;padding:1rem;">鏡頭已關閉</p>';
    document.getElementById('back-cam-container').innerHTML = '<p style="color:var(--text-muted);font-size:11px;padding:1rem;">鏡頭已關閉</p>';
}
