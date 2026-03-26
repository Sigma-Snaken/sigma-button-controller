class WS {
    constructor() {
        this._handlers = {};
        this._ws = null;
        this._reconnectDelay = 1000;
    }
    connect() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        this._ws = new WebSocket(`${proto}//${location.host}/ws`);
        this._ws.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                const handlers = this._handlers[msg.event] || [];
                handlers.forEach(h => h(msg.data));
            } catch {}
        };
        this._ws.onclose = () => {
            setTimeout(() => this.connect(), this._reconnectDelay);
        };
    }
    on(event, handler) {
        if (!this._handlers[event]) this._handlers[event] = [];
        this._handlers[event].push(handler);
    }
}
export const ws = new WS();
