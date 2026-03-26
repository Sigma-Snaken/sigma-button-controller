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
    getCamera: (id, camera, detect = false) => request('GET', `/robots/${id}/camera/${camera}${detect ? '?detect=true' : ''}`),
    startStreamer: (id, camera, detect = false) => request('POST', `/robots/${id}/streamer/${camera}${detect ? '?detect=true' : ''}`),
    stopStreamer: (id, camera) => request('DELETE', `/robots/${id}/streamer/${camera}`),
    getDetections: (id) => request('GET', `/robots/${id}/detections`),
    getMetrics: (id) => request('GET', `/robots/${id}/metrics`),

    // System
    getSystemInfo: () => request('GET', '/system/info'),
    getNotifySettings: () => request('GET', '/settings/notify'),
    updateNotifySettings: (data) => request('PUT', '/settings/notify', data),
    testNotify: () => request('POST', '/settings/notify/test'),
};
