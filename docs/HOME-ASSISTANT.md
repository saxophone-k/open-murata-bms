# Home Assistant + MQTT on the same Pi

The built-in web dashboard (`http://<pi-ip>:8080`) needs none of this. Follow this only if you want
**Home Assistant** — custom dashboards, history graphs, automations, phone alerts. Home Assistant
talks to open-murata-bms through an **MQTT broker**; the simplest setup runs the broker (and,
optionally, Home Assistant itself) on the **same Pi**. A 4 GB Pi 4 handles all three comfortably.

## 1. Install the MQTT broker (Mosquitto)

```bash
sudo apt update
sudo apt install -y mosquitto mosquitto-clients
```

Recent Mosquitto only listens on localhost and refuses anonymous clients by default. For a simple
home setup, add a small config so the engine (and Home Assistant) can connect:

```bash
sudo tee /etc/mosquitto/conf.d/omb.conf >/dev/null <<'EOF'
listener 1883
allow_anonymous true
EOF
sudo systemctl enable --now mosquitto
sudo systemctl restart mosquitto
```

> `allow_anonymous true` is fine on a trusted home network. To require a login instead, run
> `sudo mosquitto_passwd -c /etc/mosquitto/passwd youruser`, replace `allow_anonymous true` with
> `password_file /etc/mosquitto/passwd`, restart, and enter the same username/password in `omb-setup`
> and in Home Assistant.

Quick test — once the engine is running you'll see live messages:

```bash
mosquitto_sub -h localhost -t 'open-murata-bms/#' -v
```

## 2. Point open-murata-bms at the broker

```bash
cd ~/open-murata-bms
./.venv/bin/omb-setup config.yaml      # answer "yes" to Home Assistant; broker host = 127.0.0.1
sudo systemctl restart omb
```

## 3. Install Home Assistant (skip if you already run it elsewhere)

The clean way to run Home Assistant next to the engine on the same Pi is **Home Assistant Container**
(Docker) — *not* Home Assistant OS, which wants the whole machine.

```bash
sudo apt install -y docker.io
sudo docker run -d --name homeassistant --restart unless-stopped \
  --network host \
  -v ~/homeassistant:/config \
  ghcr.io/home-assistant/home-assistant:stable
```

Then open `http://<pi-ip>:8123`, create your account, and connect MQTT:

1. **Settings → Devices & Services → Add Integration → MQTT**
2. Broker: `localhost` (the `--network host` container shares the Pi's network), port `1883`, leave
   username/password empty (matching step 1).
3. Submit.

Your modules appear **automatically** as devices via MQTT discovery — each bank and module, with
voltage/current/SOC/temps, faults, and per-module availability. No manual entity setup.

---

Prefer to keep it simple? Skip all of the above and just use the built-in dashboard at
`http://<pi-ip>:8080`. You can always add Home Assistant later — turning MQTT on doesn't turn the web
dashboard off.
