#!/usr/bin/env bash
# Install ZKTeco headless agent on Linux mini PC (run as xbanana or with sudo for systemd).
set -euo pipefail

AGENT_DIR="${AGENT_DIR:-$HOME/zkteco-agent}"
SERVICE_NAME="zkteco-agent"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "==> Install dir: $AGENT_DIR"
mkdir -p "$AGENT_DIR"

# Copy agent files
cp -f "$REPO_ROOT/zkteco_core.py" "$AGENT_DIR/"
cp -f "$REPO_ROOT/zkteco_cli.py" "$AGENT_DIR/"
cp -f "$REPO_ROOT/requirements-agent.txt" "$AGENT_DIR/"
if [[ ! -f "$AGENT_DIR/config.json" ]]; then
  cp -f "$REPO_ROOT/config.example.json" "$AGENT_DIR/config.json"
  echo "    Created config.json from example — isi cloud_api_token!"
else
  echo "    Keeping existing config.json"
fi

# venv
if [[ ! -d "$AGENT_DIR/.venv" ]]; then
  python3 -m venv "$AGENT_DIR/.venv"
fi
# shellcheck disable=SC1091
source "$AGENT_DIR/.venv/bin/activate"
pip install -q --upgrade pip
pip install -q -r "$AGENT_DIR/requirements-agent.txt"

# optional .env
if [[ ! -f "$AGENT_DIR/.env" ]]; then
  cat > "$AGENT_DIR/.env" <<'EOF'
# ZKTECO_CLOUD_TOKEN=paste_token_here
# ZKTECO_CLOUD_URL=https://service.rejekiamerta.com/api/attendance
# ZKTECO_DEVICE_IP=10.10.11.55
# ZKTECO_DEVICE_PORT=8088
EOF
  chmod 600 "$AGENT_DIR/.env"
  echo "    Created .env (chmod 600) — un-comment token if not using config.json"
fi

# systemd (needs sudo)
UNIT_SRC="$SCRIPT_DIR/zkteco-agent.service"
UNIT_DST="/etc/systemd/system/${SERVICE_NAME}.service"
if [[ -w /etc/systemd/system ]] || sudo -n true 2>/dev/null; then
  # Rewrite paths for this user home if not xbanana
  TMP_UNIT=$(mktemp)
  sed "s|/home/xbanana/zkteco-agent|$AGENT_DIR|g; s|User=xbanana|User=$USER|g; s|Group=xbanana|Group=$USER|g" \
    "$UNIT_SRC" > "$TMP_UNIT"
  if [[ -w /etc/systemd/system ]]; then
    cp "$TMP_UNIT" "$UNIT_DST"
  else
    sudo cp "$TMP_UNIT" "$UNIT_DST"
  fi
  rm -f "$TMP_UNIT"
  sudo systemctl daemon-reload
  sudo systemctl enable "$SERVICE_NAME"
  echo "==> systemctl enable $SERVICE_NAME done"
  echo "    Start:  sudo systemctl start $SERVICE_NAME"
  echo "    Logs:   journalctl -u $SERVICE_NAME -f"
else
  echo "==> Skip systemd (no sudo). Manual run:"
  echo "    cd $AGENT_DIR && .venv/bin/python zkteco_cli.py daemon"
fi

echo "==> Quick checks (optional):"
echo "    cd $AGENT_DIR"
echo "    .venv/bin/python zkteco_cli.py test-device"
echo "    .venv/bin/python zkteco_cli.py test-cloud"
echo "    .venv/bin/python zkteco_cli.py run-once"
echo "Done."
