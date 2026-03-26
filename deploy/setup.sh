#!/bin/bash
set -euo pipefail

echo "=== Sigma Button Controller — First-time Setup ==="

# ── Docker (for Mosquitto + Zigbee2MQTT) ──
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo "Docker installed. Please log out and back in, then re-run this script."
    exit 0
fi

# ── Python + uv (for FastAPI app) ──
if ! command -v python3 &> /dev/null; then
    echo "Installing Python..."
    sudo apt-get update && sudo apt-get install -y python3 python3-venv
fi

if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# ── Zigbee dongle udev rule ──
echo "Setting up Zigbee dongle udev rule..."
echo 'SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", SYMLINK+="zigbee"' | sudo tee /etc/udev/rules.d/99-zigbee.rules > /dev/null
sudo udevadm control --reload-rules && sudo udevadm trigger
if [ -e /dev/zigbee ]; then
    echo "Zigbee dongle found at /dev/zigbee -> $(readlink /dev/zigbee)"
else
    echo "Warning: Zigbee dongle not detected. Plug it in and run: sudo udevadm trigger"
fi

# ── App directory ──
APP_DIR=/opt/app/sigma-button-controller
sudo mkdir -p "$APP_DIR"
sudo chown "$USER:$USER" "$APP_DIR"

cp docker-compose.yml "$APP_DIR/"
mkdir -p "$APP_DIR/data" "$APP_DIR/mosquitto" "$APP_DIR/zigbee2mqtt"

# ── Download app source ──
echo "Downloading app source..."
curl -L https://github.com/Sigma-Snaken/sigma-button-controller/archive/refs/heads/main.tar.gz \
    | tar xz --strip=1 -C "$APP_DIR" sigma-button-controller-main/src sigma-button-controller-main/requirements.txt

# ── Python venv + dependencies ──
echo "Installing Python dependencies..."
uv venv "$APP_DIR/.venv"
uv pip install --python "$APP_DIR/.venv/bin/python" -r "$APP_DIR/requirements.txt"

# ── Mosquitto config ──
if [ ! -f "$APP_DIR/mosquitto/mosquitto.conf" ]; then
    cat > "$APP_DIR/mosquitto/mosquitto.conf" << 'CONF'
listener 1883
allow_anonymous true
persistence true
persistence_location /mosquitto/data/
log_dest stdout
CONF
fi

# ── Zigbee2MQTT config ──
if [ ! -f "$APP_DIR/zigbee2mqtt/configuration.yaml" ]; then
    cat > "$APP_DIR/zigbee2mqtt/configuration.yaml" << 'CONF'
mqtt:
  base_topic: zigbee2mqtt
  server: mqtt://mosquitto
serial:
  port: /dev/zigbee
  adapter: ezsp
frontend:
  port: 8080
advanced:
  log_level: info
permit_join: false
CONF
fi

# ── Polkit rule for WiFi management ──
echo "Setting up WiFi management permissions..."
sudo tee /etc/polkit-1/rules.d/50-sigma-wifi.rules > /dev/null << 'RULE'
polkit.addRule(function(action, subject) {
    if (action.id.indexOf("org.freedesktop.NetworkManager") === 0 &&
        subject.user === "sigma") {
        return polkit.Result.YES;
    }
});
RULE

# ── Systemd service ──
echo "Installing systemd service..."
sudo cp sigma-app.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sigma-app

# ── Desktop shortcut ──
DESKTOP_DIR="$HOME/Desktop"
if [ -d "$DESKTOP_DIR" ]; then
    cat > "$DESKTOP_DIR/sigma-controller.desktop" << 'SHORTCUT'
[Desktop Entry]
Type=Link
Name=Sigma 控制介面
Comment=Zigbee → Kachaka Controller
Icon=applications-internet
URL=http://localhost:8000
SHORTCUT
    chmod +x "$DESKTOP_DIR/sigma-controller.desktop"
    echo "Desktop shortcut created."
fi

echo ""
echo "=== Setup complete ==="
echo "Next steps:"
echo "  1. Verify Zigbee dongle: ls -la /dev/zigbee"
echo "  2. cd $APP_DIR && docker compose pull && docker compose up -d"
echo "  3. sudo systemctl start sigma-app"
