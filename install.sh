#!/usr/bin/env bash
# open-murata-bms — one-command installer for a Raspberry Pi (or any Debian/Ubuntu Linux).
#
#   curl -fsSL https://raw.githubusercontent.com/saxophone-k/open-murata-bms/main/install.sh | bash
#
# Installs natively (Python venv + a systemd service) — NO Docker. Sets up serial access, the
# FTDI speed fix, runs an interactive setup to write your config, starts the service, and prints
# the dashboard URL. Re-run any time to update. See the README for the full beginner guide.
set -euo pipefail

REPO="https://github.com/saxophone-k/open-murata-bms.git"
DIR="$HOME/open-murata-bms"
ME="$(id -un)"

say() { printf '\n\033[1;32m>>> %s\033[0m\n' "$1"; }

command -v sudo >/dev/null || { echo "This installer needs sudo."; exit 1; }
[ -e /dev/tty ] || { echo "No terminal available for setup. Run install.sh directly on the Pi."; exit 1; }

say "Installing prerequisites (python, git)…"
sudo apt-get update -qq
sudo apt-get install -y python3 python3-venv python3-pip git

say "Fetching open-murata-bms…"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only
else
  git clone --depth 1 "$REPO" "$DIR"
fi
cd "$DIR"

say "Setting up the Python environment…"
python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet .

say "Granting serial-port access + installing the USB speed fix…"
sudo usermod -aG dialout "$ME" || true
sudo cp packaging/99-ftdi-latency.rules /etc/udev/rules.d/ 2>/dev/null || true
sudo udevadm control --reload-rules 2>/dev/null || true
sudo udevadm trigger 2>/dev/null || true

if [ ! -f "$DIR/config.yaml" ]; then
  say "Let's set up your battery system…"
  ./.venv/bin/omb-setup "$DIR/config.yaml" < /dev/tty
fi

say "Installing the background service (starts on boot)…"
sudo tee /etc/systemd/system/omb.service >/dev/null <<UNIT
[Unit]
Description=open-murata-bms — Murata battery monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$ME
SupplementaryGroups=dialout
WorkingDirectory=$DIR
Environment=PYTHONIOENCODING=utf-8
ExecStartPre=+/bin/sh -c 'for d in /sys/bus/usb-serial/devices/ttyUSB*/latency_timer; do echo 1 > "\$d" 2>/dev/null || true; done'
ExecStart=$DIR/.venv/bin/omb --config $DIR/config.yaml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now omb.service

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
say "Done! Your battery dashboard is live:"
printf '\n      \033[1;36mhttp://%s:8080\033[0m\n\n' "${IP:-<this-pi-ip>}"
echo "  • Check it:   systemctl status omb"
echo "  • Live logs:  journalctl -u omb -f"
echo "  • Reconfigure: cd $DIR && ./.venv/bin/omb-setup config.yaml && sudo systemctl restart omb"
