#!/bin/bash
set -euo pipefail

echo "=== Sigma Button Controller — First-time Setup ==="

if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo "Docker installed. Please log out and back in, then re-run this script."
    exit 0
fi

# Create udev rule for Zigbee dongle (fixed /dev/zigbee symlink)
echo "Setting up Zigbee dongle udev rule..."
echo 'SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", SYMLINK+="zigbee"' | sudo tee /etc/udev/rules.d/99-zigbee.rules > /dev/null
sudo udevadm control --reload-rules && sudo udevadm trigger
if [ -e /dev/zigbee ]; then
    echo "Zigbee dongle found at /dev/zigbee -> $(readlink /dev/zigbee)"
else
    echo "Warning: Zigbee dongle not detected. Plug it in and run: sudo udevadm trigger"
fi

APP_DIR=/opt/app/sigma-button-controller
sudo mkdir -p "$APP_DIR"
sudo chown "$USER:$USER" "$APP_DIR"

cp docker-compose.yml "$APP_DIR/"
mkdir -p "$APP_DIR/data" "$APP_DIR/mosquitto" "$APP_DIR/zigbee2mqtt"

if [ ! -f "$APP_DIR/mosquitto/mosquitto.conf" ]; then
    cat > "$APP_DIR/mosquitto/mosquitto.conf" << 'CONF'
listener 1883
allow_anonymous true
persistence true
persistence_location /mosquitto/data/
log_dest stdout
CONF
fi

if [ ! -f "$APP_DIR/zigbee2mqtt/configuration.yaml" ]; then
    cat > "$APP_DIR/zigbee2mqtt/configuration.yaml" << 'CONF'
mqtt:
  base_topic: zigbee2mqtt
  server: mqtt://mosquitto
serial:
  port: /dev/zigbee
frontend:
  port: 8080
advanced:
  log_level: info
permit_join: false
CONF
fi

# Create desktop shortcut
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
