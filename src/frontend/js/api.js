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
    getShortcuts: (id) => request('GET', `/robots/${id}/shortcuts`),
    listButtons: () => request('GET', '/buttons'),
    updateButton: (id, data) => request('PUT', `/buttons/${id}`, data),
    deleteButton: (id) => request('DELETE', `/buttons/${id}`),
    startPairing: () => request('POST', '/buttons/pair'),
    stopPairing: () => request('POST', '/buttons/pair/stop'),
    getBindings: (buttonId) => request('GET', `/bindings/${buttonId}`),
    updateBindings: (buttonId, data) => request('PUT', `/bindings/${buttonId}`, data),
    getLogs: (page = 1) => request('GET', `/logs?page=${page}`),
};
