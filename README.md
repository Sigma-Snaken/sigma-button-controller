# Sigma Button Controller

[![Build & Push](https://github.com/Sigma-Snaken/sigma-button-controller/actions/workflows/build.yml/badge.svg)](https://github.com/Sigma-Snaken/sigma-button-controller/actions/workflows/build.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

Zigbee 按鈕 → Kachaka 機器人控制器。透過 Web UI 配對 SONOFF SNZB-01 按鈕，將單擊/雙擊/長按綁定到 Kachaka 動作（移動、搬貨架、語音播報等），一鍵觸發。運行於 Raspberry Pi 5。

## 功能

- **多機器人管理** — 動態新增/移除 Kachaka，即時狀態與電量
- **Zigbee 按鈕配對** — Web UI 一鍵 permit_join，自動偵測 SNZB-01
- **三觸發綁定** — 單擊/雙擊/長按各自綁定不同動作，參數從機器人即時載入
- **8 種機器人動作** — 移動、回充電座、語音、搬運/歸還貨架、對接/放下、執行捷徑
- **機器人監控** — 即時地圖 + 位置、前/後鏡頭串流 (5 FPS)、RTT 熱力圖
- **WiFi 設定 + AP 配網** — 搬到新環境時，手機連 AP 即可設定 WiFi
- **執行記錄** — 完整歷史含錯誤代碼，支援分頁
- **Telegram 通知** — 執行失敗自動推送
- **RWD** — 桌面/平板/手機自適應，手機版 FAB 浮動選單

## 硬體架構

```mermaid
graph LR
    subgraph LAN["區域網路"]
        Pi["Raspberry Pi 5<br/>:8000 Web UI"]
        K1["Kachaka Robot<br/>:26400 gRPC"]
        K2["Kachaka Robot N<br/>:26400 gRPC"]
    end
    Dongle["SONOFF Zigbee 3.0<br/>USB Dongle<br/>/dev/zigbee"] -->|USB| Pi
    BTN["SNZB-01 按鈕"] -.->|Zigbee 3.0| Dongle
    Pi -->|gRPC| K1
    Pi -->|gRPC| K2
    User["瀏覽器 / 手機"] -->|HTTP| Pi
```

## 軟體架構

```mermaid
graph TD
    subgraph Pi["Raspberry Pi 5"]
        subgraph Docker["Docker Compose"]
            MQTT["Mosquitto :1883"]
            Z2M["Zigbee2MQTT :8080"]
            subgraph App["FastAPI App :8000"]
                direction TB
                Routers["Routers"]
                Services["Services"]
                SDK["kachaka_core"]
                DB[("SQLite WAL")]
                FE["Frontend SPA"]
            end
        end
        WA["WiFi Agent :8001<br/>(systemd, nmcli)"]
    end

    SNZB["SNZB-01"] -.->|Zigbee| Z2M
    Z2M <-->|MQTT| MQTT
    MQTT --> Services
    Services --> SDK
    SDK -->|gRPC| Kachaka["Kachaka Robots"]
    App -->|HTTP localhost| WA
    Browser["Browser"] -->|HTTP/WS| FE
```

### 部署架構

| 元件 | 部署方式 | 原因 |
|------|---------|------|
| Mosquitto | Docker | 獨立服務 |
| Zigbee2MQTT | Docker | device passthrough |
| FastAPI App | Docker | 環境隔離，GHCR pull 更新 |
| WiFi Agent | systemd (host) | 需要 nmcli，50 行 stdlib script |

### 核心設計原則

- **單 worker** — 機器人一次一個命令，多 worker 無意義且造成 state 衝突
- **非阻塞讀取** — 狀態一律從 `controller.state` / `conn.state` 讀取（記憶體，零 I/O）
- **sync gRPC 走 executor** — 寫入操作用 `run_in_executor` 避免阻塞 event loop
- **CameraStreamer** — 背景 thread 拉幀，HTTP handler 只讀 `latest_frame`

## 資料流

### 按鈕觸發 → 機器人動作

```mermaid
sequenceDiagram
    participant B as SNZB-01
    participant Z as Zigbee2MQTT
    participant M as Mosquitto
    participant BM as ButtonManager
    participant AE as ActionExecutor
    participant K as Kachaka

    B->>Z: Zigbee 按壓
    Z->>M: MQTT {"action":"single"}
    M->>BM: 解析事件 + 查詢綁定
    BM->>AE: execute(robot_id, action, params)
    Note over AE: run_in_executor
    AE->>K: gRPC (move/speak/shelf...)
    K-->>AE: result
    AE-->>BM: 寫入 log + WebSocket 廣播
```

### WiFi AP 配網

```mermaid
sequenceDiagram
    participant U as 手機
    participant Pi as Raspberry Pi

    Note over Pi: WiFi 連不上或手動觸發
    Pi->>Pi: nmcli hotspot (SIGMA-SETUP)
    U->>Pi: 連上 AP → http://10.42.0.1:8000
    U->>Pi: 掃描網路 → 選擇 SSID → 輸入密碼
    Pi->>Pi: nmcli connect 新網路
    Note over Pi: AP 關閉，切回 client 模式
```

## 快速開始

### 硬體需求

- Raspberry Pi 5 (或任何 Linux amd64/arm64)
- SONOFF Zigbee 3.0 USB Dongle Plus
- SONOFF SNZB-01 按鈕 (一個或多個)
- Kachaka 機器人 (同一區域網路)

### 生產部署

**1. 下載部署檔案**

```bash
curl -L https://github.com/Sigma-Snaken/sigma-button-controller/archive/refs/heads/main.tar.gz \
    | tar xz --strip=1 sigma-button-controller-main/deploy
cd deploy
```

**2. 首次設定 (Docker + udev + systemd)**

```bash
chmod +x setup.sh && ./setup.sh
```

> 首次安裝 Docker 後，腳本會自動停止並提示重新登入。
> 請登出再登入（或 `sudo reboot`），然後再執行一次 `./setup.sh` 完成剩餘設定。

**3. 啟動所有服務 (Mosquitto + Z2M + App)**

```bash
cd /opt/app/sigma-button-controller
docker compose pull && docker compose up -d
```

**4. 啟動 WiFi agent**

```bash
sudo systemctl start sigma-wifi
```

> **Docker 網段注意**
>
> `setup.sh` 會將 Docker 內部網段限縮為 `10.255.255.0/24`（寫入 `/etc/docker/daemon.json`），
> 避免 Docker 預設佔用 `172.17~172.31` 網段導致與實體 LAN（如 `172.20.10.x`）衝突。
> 若上位網路恰好使用 `10.255.255.x` 網段，需手動修改 `daemon.json` 中的 `base` 為其他不衝突的私有網段。

> **Zigbee Dongle 注意**
>
> `setup.sh` 建立 udev rule 將 dongle 固定為 `/dev/zigbee`。預設針對 SONOFF (USB ID `10c4:ea60`)。
> 其他廠牌需修改：
> ```bash
> udevadm info -a -n /dev/ttyUSB0 | grep -E 'idVendor|idProduct'
> sudo nano /etc/udev/rules.d/99-zigbee.rules
> sudo udevadm control --reload-rules && sudo udevadm trigger
> ```

### 開發環境

```bash
git clone https://github.com/Sigma-Snaken/sigma-button-controller.git
cd sigma-button-controller
docker compose up --build
# docker-compose.override.yml 自動套用：src/ volume mount + --reload
```

### 存取服務

| 服務 | URL |
|------|-----|
| 控制介面 | `http://<IP>:8000` |
| Zigbee2MQTT | `http://<IP>:8080` |

## 技術棧

| 層級 | 技術 |
|------|------|
| 後端 | Python 3.12, FastAPI, uvicorn, aiomqtt, aiosqlite, httpx |
| 機器人 SDK | [kachaka-sdk-toolkit](https://github.com/Sigma-Snaken/kachaka-sdk-toolkit) |
| 前端 | Vanilla JS ES Modules, CSS3 |
| 資料庫 | SQLite WAL, 版本化 migration |
| MQTT | Eclipse Mosquitto 2 |
| Zigbee | Zigbee2MQTT + SONOFF Dongle |
| CI/CD | GitHub Actions → GHCR (amd64 + arm64) |

## API 端點

### 機器人

| Method | Endpoint | 說明 |
|--------|----------|------|
| GET | `/api/robots` | 列表 (online/battery/serial 從 controller.state 讀取) |
| POST | `/api/robots` | 新增 |
| PUT | `/api/robots/{id}` | 更新 |
| DELETE | `/api/robots/{id}` | 刪除 |
| GET | `/api/robots/{id}/locations` | 位置清單 |
| GET | `/api/robots/{id}/shelves` | 貨架清單 |
| GET | `/api/robots/{id}/shortcuts` | 捷徑清單 |

### 監控

| Method | Endpoint | 說明 |
|--------|----------|------|
| GET | `/api/robots/{id}/map` | 地圖 + 位置 (pose 從 controller.state) |
| GET | `/api/robots/{id}/camera/{front\|back}` | 鏡頭 (CameraStreamer latest_frame) |
| POST | `/api/robots/{id}/camera/{cam}/start` | 啟動串流 |
| POST | `/api/robots/{id}/camera/{cam}/stop` | 停止串流 |
| GET | `/api/robots/{id}/metrics` | RTT 統計 |
| GET | `/api/robots/{id}/rtt-heatmap` | 熱力圖資料 |
| DELETE | `/api/robots/{id}/rtt-heatmap` | 清除 RTT |

### 按鈕 & 綁定

| Method | Endpoint | 說明 |
|--------|----------|------|
| GET | `/api/buttons` | 按鈕列表 |
| PUT | `/api/buttons/{id}` | 重命名 |
| DELETE | `/api/buttons/{id}` | 刪除 |
| POST | `/api/buttons/pair` | 啟動配對 (120s) |
| POST | `/api/buttons/pair/stop` | 停止配對 |
| GET | `/api/bindings/{button_id}` | 查詢綁定 |
| PUT | `/api/bindings/{button_id}` | 更新綁定 |

### WiFi

| Method | Endpoint | 說明 |
|--------|----------|------|
| GET | `/api/wifi/status` | 連線狀態 (SSID/IP/signal/mode) |
| POST | `/api/wifi/scan` | 掃描可用網路 |
| POST | `/api/wifi/connect` | 連線 WiFi |
| POST | `/api/wifi/hotspot/start` | 啟動 AP |
| POST | `/api/wifi/hotspot/stop` | 關閉 AP |

### 系統

| Method | Endpoint | 說明 |
|--------|----------|------|
| GET | `/api/health` | 健康檢查 |
| GET | `/api/system/info` | 系統 URL |
| GET | `/api/settings/notify` | Telegram 設定 |
| PUT | `/api/settings/notify` | 更新 Telegram |
| POST | `/api/settings/notify/test` | 測試通知 |
| GET | `/api/logs?page=N` | 執行記錄 |
| WS | `/ws` | 即時事件 |

### 支援的動作

| 動作 | 參數 | 執行方式 |
|------|------|----------|
| `move_to_location` | `{name}` | RobotController |
| `return_home` | — | RobotController |
| `move_shelf` | `{shelf, location}` | RobotController |
| `return_shelf` | `{shelf}` | RobotController |
| `speak` | `{text}` | KachakaCommands |
| `dock_shelf` | — | KachakaCommands |
| `undock_shelf` | — | KachakaCommands |
| `start_shortcut` | `{shortcut_id}` | KachakaCommands |

## 資料庫

SQLite WAL, 3 版本 migration:

| 表 | 用途 | 版本 |
|----|------|------|
| `robots` | 機器人 (id, name, ip, enabled) | V1 |
| `buttons` | 按鈕 (ieee_addr, battery, last_seen) | V1 |
| `bindings` | 綁定 (trigger, action, UNIQUE) | V1 |
| `action_logs` | 執行記錄 | V1 |
| `settings` | KV 設定 | V2 |
| `rtt_logs` | RTT 記錄 (x, y, rtt_ms, battery) | V3 |

## 測試

```bash
uv venv .venv && uv pip install -r requirements.txt
.venv/bin/pytest tests/ -v
```

## 專案結構

```
sigma-button-controller/
├── src/
│   ├── backend/
│   │   ├── main.py                  # FastAPI + lifespan
│   │   ├── routers/                 # 8 個路由模組
│   │   ├── services/                # 8 個服務模組
│   │   ├── database/                # connection + migrations
│   │   └── utils/
│   └── frontend/
│       ├── index.html               # SPA (6 個 Tab)
│       ├── css/style.css            # Vintage Terminal 主題 + RWD
│       └── js/                      # 9 個 ES Modules
├── deploy/
│   ├── docker-compose.yml           # Mosquitto + Z2M + App
│   ├── wifi-agent.py                # WiFi 管理 (host, stdlib only)
│   ├── sigma-wifi.service           # WiFi agent systemd service
│   └── setup.sh                     # 首次部署腳本
├── mosquitto/                       # Mosquitto 設定
├── zigbee2mqtt/                     # Z2M 設定
├── tests/                           # pytest
├── docker-compose.yml               # 開發用
├── Dockerfile
├── .github/workflows/build.yml      # CI: GHCR
└── requirements.txt
```

## License

Copyright 2026 Sigma Robotics. Licensed under the [Apache License 2.0](LICENSE).
