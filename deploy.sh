#!/usr/bin/env bash
# One-shot install of Castle Quartermaster on a Debian/Ubuntu box. Fine to run on the same Google Cloud VM as
# Mo Betta Bot: it gets its own folder, its own service and its own token.
#
#   curl -fsSL https://raw.githubusercontent.com/amyklindley/castle-quartermaster/main/deploy.sh -o deploy.sh && bash deploy.sh
#
# What it does: installs Python + git, clones the repo to /opt/castle-quartermaster, creates a virtualenv, asks for the
# Discord token and server id once, and installs a systemd service that starts the bot on boot and restarts it
# if it ever dies. Safe to re-run: it updates the code and restarts the service. The ticket database
# (tickets.db) lives in that folder and is never touched by updates.
set -euo pipefail

REPO="https://github.com/amyklindley/castle-quartermaster"
DIR="/opt/castle-quartermaster"
SVC="castle-quartermaster"
USER_NAME="${SUDO_USER:-$USER}"

echo "== Castle Quartermaster installer =="
if [ -n "${CLOUD_SHELL:-}" ] || [ -n "${DEVSHELL_PROJECT_ID:-}" ]; then
  echo "This is Google Cloud Shell, which is wiped when you close it. Run this on the VM instead:"
  echo "Compute Engine -> VM instances -> SSH button on your instance, then paste the command there."
  exit 1
fi
sudo apt-get update -qq </dev/null
sudo apt-get install -y -qq python3 python3-venv git >/dev/null </dev/null

if [ -d "$DIR/.git" ]; then
  echo "-- updating $DIR"
  sudo -u "$USER_NAME" git -C "$DIR" pull -q
else
  echo "-- cloning into $DIR"
  sudo mkdir -p "$DIR"
  sudo chown "$USER_NAME" "$DIR"
  sudo -u "$USER_NAME" git clone -q "$REPO" "$DIR"
fi

echo "-- python packages"
sudo -u "$USER_NAME" python3 -m venv "$DIR/.venv"
sudo -u "$USER_NAME" "$DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u "$USER_NAME" "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"

if [ ! -f "$DIR/.env" ]; then
  echo
  echo "Paste the Castle Quartermaster bot token from https://discord.com/developers/applications (Bot -> Reset Token)."
  echo "This is a different bot from Mo Betta, so it's a different token. Nothing shows while you paste; press Enter."
  read -r -s -p "DISCORD_TOKEN: " TOKEN </dev/tty
  echo
  read -r -p "GUILD_ID (the guild's Discord server id): " GUILD </dev/tty
  sudo -u "$USER_NAME" bash -c "umask 077; printf 'DISCORD_TOKEN=%s\nGUILD_ID=%s\n' '$TOKEN' '$GUILD' > '$DIR/.env'"
  echo "-- wrote $DIR/.env (readable only by $USER_NAME)"
fi

echo "-- systemd service"
sudo tee /etc/systemd/system/$SVC.service >/dev/null <<UNIT
[Unit]
Description=Castle Quartermaster (crafting, gathering and guild bank requests)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python $DIR/bot.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable -q $SVC
sudo systemctl restart $SVC
sleep 6
echo
sudo systemctl --no-pager --lines=8 status $SVC || true
echo
echo "Done. Useful later:"
echo "  sudo journalctl -u $SVC -f        follow the bot's log"
echo "  sudo systemctl restart $SVC       restart it"
echo "  cp $DIR/tickets.db ~/tickets-backup.db    back up the tickets"
echo "  curl -fsSL $REPO/raw/main/deploy.sh -o deploy.sh && bash deploy.sh    update to the latest code"
