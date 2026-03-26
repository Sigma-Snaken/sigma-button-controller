import { api } from './api.js';
import { showToast } from './app.js';

const container = document.getElementById('monitor');
let mapTimer = null;
let frontCamTimer = null;
let backCamTimer = null;

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
        loadMap(sel.value);
        resetCamButtons();
    });

    container.querySelector('#toggle-front-cam').addEventListener('click', (e) => toggleCamera(sel.value, 'front', e.target));
    container.querySelector('#toggle-back-cam').addEventListener('click', (e) => toggleCamera(sel.value, 'back', e.target));

    loadMap(sel.value);
}

async function loadMap(robotId) {
    if (mapTimer) { clearInterval(mapTimer); mapTimer = null; }

    const draw = async () => {
        try {
            const data = await api.getMap(robotId);
            if (!data.ok) return;
            drawMap(data.map, data.pose);
        } catch (e) {
            console.error('Map load error:', e);
        }
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
        // Scale map to fit (max 500px wide)
        const scale = Math.min(500 / img.width, 400 / img.height, 1);
        canvas.width = img.width * scale;
        canvas.height = img.height * scale;

        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

        if (pose) {
            // Convert world coords to pixel coords
            const res = map.resolution || 0.025;
            const ox = map.origin_x || 0;
            const oy = map.origin_y || 0;
            const mapH = map.height || img.height;

            const px = ((pose.x - ox) / res) * scale;
            const py = ((mapH - (pose.y - oy) / res)) * scale;

            // Draw robot position
            ctx.beginPath();
            ctx.arc(px, py, 8, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(220, 53, 69, 0.8)';
            ctx.fill();
            ctx.strokeStyle = 'white';
            ctx.lineWidth = 2;
            ctx.stroke();

            // Draw direction arrow
            const arrowLen = 16;
            const angle = -pose.theta; // canvas Y is flipped
            const ax = px + Math.cos(angle) * arrowLen;
            const ay = py - Math.sin(angle) * arrowLen;
            ctx.beginPath();
            ctx.moveTo(px, py);
            ctx.lineTo(ax, ay);
            ctx.strokeStyle = 'rgba(220, 53, 69, 0.9)';
            ctx.lineWidth = 3;
            ctx.stroke();

            // Arrow head
            const headLen = 6;
            const a1 = angle + Math.PI * 0.8;
            const a2 = angle - Math.PI * 0.8;
            ctx.beginPath();
            ctx.moveTo(ax, ay);
            ctx.lineTo(ax + Math.cos(a1) * headLen, ay - Math.sin(a1) * headLen);
            ctx.moveTo(ax, ay);
            ctx.lineTo(ax + Math.cos(a2) * headLen, ay - Math.sin(a2) * headLen);
            ctx.stroke();

            // Update pose info text
            const info = document.getElementById('pose-info');
            if (info) info.textContent = `x: ${pose.x.toFixed(2)}, y: ${pose.y.toFixed(2)}, θ: ${(pose.theta * 180 / Math.PI).toFixed(1)}°`;
        }
    };
    img.src = `data:image/${map.format || 'png'};base64,${map.image_base64}`;
}

function toggleCamera(robotId, camera, btn) {
    const containerId = camera === 'front' ? 'front-cam-container' : 'back-cam-container';
    const timerRef = camera === 'front' ? 'frontCamTimer' : 'backCamTimer';
    const container = document.getElementById(containerId);

    if (btn.textContent === '開啟') {
        btn.textContent = '關閉';
        btn.classList.add('btn-danger');
        btn.classList.remove('btn-success');
        startCameraStream(robotId, camera, container);
    } else {
        btn.textContent = '開啟';
        btn.classList.remove('btn-danger');
        btn.classList.add('btn-success');
        stopCameraStream(camera);
        container.innerHTML = '<p style="color:var(--text-muted);font-size:11px;padding:1rem;">鏡頭已關閉</p>';
    }
}

function startCameraStream(robotId, camera, container) {
    container.innerHTML = '<img id="' + camera + '-cam-img" style="width:100%;max-width:400px;border-radius:4px;display:block;" /><p style="color:var(--text-muted);font-size:10px;margin-top:0.25rem" id="' + camera + '-cam-status">載入中...</p>';

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
    if (camera === 'front') {
        frontCamTimer = setInterval(fetchFrame, 2000);
    } else {
        backCamTimer = setInterval(fetchFrame, 2000);
    }
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
