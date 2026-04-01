const BASE = '/api';

async function request(method, path, body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(BASE + path, opts);
    if (!resp.ok) {
        const err = await resp.text();
        throw new Error(err);
    }
    return resp.json();
}

export const api = {
    listRobots: () => request('GET', '/robots'),
    createRobot: (data) => request('POST', '/robots', data),
    updateRobot: (id, data) => request('PUT', `/robots/${id}`, data),
    deleteRobot: (id) => request('DELETE', `/robots/${id}`),
    getLocations: (id) => request('GET', `/robots/${id}/locations`),
    getShelves: (id) => request('GET', `/robots/${id}/shelves`),
    getShortcuts: (id) => request('GET', `/robots/${id}/shortcuts`),
    listButtons: () => request('GET', '/buttons'),
    updateButton: (id, data) => request('PUT', `/buttons/${id}`, data),
    deleteButton: (id) => request('DELETE', `/buttons/${id}`),
    startPairing: () => request('POST', '/buttons/pair'),
    stopPairing: () => request('POST', '/buttons/pair/stop'),
    getBindings: (buttonId) => request('GET', `/bindings/${buttonId}`),
    updateBindings: (buttonId, data) => request('PUT', `/bindings/${buttonId}`, data),
    getLogs: (page = 1) => request('GET', `/logs?page=${page}`),

    // Monitor
    getMap: (id) => request('GET', `/robots/${id}/map`),
    getCamera: (id, camera) => request('GET', `/robots/${id}/camera/${camera}`),
    startCamera: (id, camera) => request('POST', `/robots/${id}/camera/${camera}/start`),
    stopCamera: (id, camera) => request('POST', `/robots/${id}/camera/${camera}/stop`),
    getRttHeatmap: (id, limit = 500) => request('GET', `/robots/${id}/rtt-heatmap?limit=${limit}`),
    clearRttHeatmap: (id) => request('DELETE', `/robots/${id}/rtt-heatmap`),

    // WiFi
    getWifiStatus: () => request('GET', '/wifi/status'),
    scanWifi: () => request('POST', '/wifi/scan'),
    connectWifi: (data) => request('POST', '/wifi/connect', data),
    startHotspot: (data) => request('POST', '/wifi/hotspot/start', data),
    stopHotspot: () => request('POST', '/wifi/hotspot/stop'),

    // System
    getSystemInfo: () => request('GET', '/system/info'),
    getNotifySettings: () => request('GET', '/settings/notify'),
    updateNotifySettings: (data) => request('PUT', '/settings/notify', data),
    testNotify: () => request('POST', '/settings/notify/test'),

    // Queue
    getQueue: () => request('GET', '/queue'),
    removeFromQueue: (id) => request('DELETE', `/queue/${id}`),
    cancelCurrent: (robotId) => request('POST', `/queue/cancel/${robotId}`),
    getQueueSettings: () => request('GET', '/settings/queue'),
    updateQueueSettings: (data) => request('PUT', '/settings/queue', data),
};
