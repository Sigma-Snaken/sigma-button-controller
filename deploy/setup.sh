#!/bin/bash
set -euo pipefail

echo "=== Pi Zigbee Controller — First-time Setup ==="

if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo "Docker installed. Please log out and back in, then re-run this script."
    exit 0
fi

echo "Configuring Docker daemon..."
sudo cp daemon.json /etc/docker/daemon.json
sudo systemctl restart docker

APP_DIR=/opt/app/pi-zigbee
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
  port: /dev/ttyACM0
frontend:
  port: 8080
advanced:
  log_level: info
permit_join: false
CONF
fi

if [ ! -f "$APP_DIR/.env" ]; then
    cp .env.example "$APP_DIR/.env"
    echo "Created .env from template. Edit $APP_DIR/.env if needed."
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
echo "  1. Verify Zigbee dongle: ls /dev/ttyACM* /dev/ttyUSB*"
echo "  2. Edit $APP_DIR/.env if the device path differs"
echo "  3. cd $APP_DIR && docker compose pull && docker compose up -d"
