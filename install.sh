#!/usr/bin/env bash
# Install vllm-chat as a systemd service on this box.
#   bash install.sh            # port 80
#   PORT=8501 bash install.sh  # any other port
# Steps: install streamlit (uv if present, else pip --user), create servers.toml from the example if missing,
# render the unit for this user/dir, then run the sudo part (printed first so you can see it).
set -e
DIR=$(cd "$(dirname "$0")" && pwd); PORT=${PORT:-80}; UNIT=vllm-chat
if command -v uv >/dev/null; then
  uv tool install --force --with requests --with watchdog streamlit >/dev/null
  STREAMLIT=$(command -v streamlit || echo "$HOME/.local/bin/streamlit")
else
  python3 -m pip install --user -r "$DIR/requirements.txt" >/dev/null
  STREAMLIT=$(command -v streamlit || echo "$HOME/.local/bin/streamlit")
fi
[ -f "$DIR/servers.toml" ] || cp "$DIR/servers.example.toml" "$DIR/servers.toml"
sed -e "s|__USER__|$USER|g" -e "s|__DIR__|$DIR|g" -e "s|__STREAMLIT__|$STREAMLIT|g" -e "s|__PORT__|$PORT|g" \
    "$DIR/$UNIT.service" > "/tmp/$UNIT.service"
echo "streamlit: $STREAMLIT"; echo "config:    $DIR/servers.toml  (edit this for your servers)"; echo
echo "installing service (sudo):"
set -x
sudo install -m644 "/tmp/$UNIT.service" /etc/systemd/system/$UNIT.service
sudo systemctl daemon-reload
sudo systemctl enable --now $UNIT
set +x
sleep 3; systemctl is-active $UNIT && echo "open http://$(hostname -I | awk '{print $1}'):$PORT/"
