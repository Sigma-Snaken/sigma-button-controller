#!/bin/bash
set -euo pipefail

echo "=== Sigma Button Controller — First-time Setup ==="

# ── Docker ──
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo "Docker installed. Please log out and back in, then re-run this script."
    exit 0
fi

# ── Docker network: restrict to 10.255.255.0/24 to avoid LAN conflicts ──
DAEMON_JSON=/etc/docker/daemon.json
if [ ! -f "$DAEMON_JSON" ] || ! grep -q default-address-pools "$DAEMON_JSON"; then
    echo "Configuring Docker subnet (10.255.255.0/24)..."
    sudo tee "$DAEMON_JSON" > /dev/null << 'JSON'
{
  "default-address-pools": [
    { "base": "10.255.255.0/24", "size": 28 }
  ]
}
JSON
    sudo systemctl restart docker
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

# ── WiFi agent (host service, stdlib only) ──
echo "Installing WiFi agent..."
cp wifi-agent.py "$APP_DIR/"

# Polkit rule for NetworkManager access
sudo tee /etc/polkit-1/rules.d/50-sigma-wifi.rules > /dev/null << 'RULE'
polkit.addRule(function(action, subject) {
    if (action.id.indexOf("org.freedesktop.NetworkManager") === 0 &&
        subject.user === "sigma") {
        return polkit.Result.YES;
    }
});
RULE

sudo cp sigma-wifi.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sigma-wifi

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
echo "  3. sudo systemctl start sigma-wifi"
