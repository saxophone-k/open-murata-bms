# open-murata-bms

An open, config-driven monitor for **Murata IJ1101M ("Fortelion") battery modules** — polling them
over Modbus RTU/TCP, aggregating a whole bank, and showing everything either in a **built-in web
dashboard** (nothing else to install) or in **Home Assistant over MQTT**. Works whether you have
**one module or many**, **with or without a Murata BMU**.

> ⚠️ **This software talks to a live high-energy battery bank.** Read **[SAFETY.md](SAFETY.md)**
> first. It **monitors; it does not protect or disconnect anything** — you must have
> your own way to cut the current (see the guide). It is **read-only by default**; every write path
> is off-by-default and guarded. You are responsible for your own hardware.

### 🔰 New to this? → **[Complete Beginner Guide](docs/GETTING-STARTED.md)**

From zero to a live dashboard: shopping list, wiring, flashing the Pi, one-command install. Start there.

![How it works: a Raspberry Pi polls a daisy chain of battery modules over RS-485](docs/img/daisy-chain.svg)

## Status

**Monitoring works end-to-end and is validated on real hardware** (an 18-module bank: fresh
install → poll → web dashboard + Home Assistant, self-healing across module/adapter unplugs and
reboots). See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the design.

## Two ways to run it — your choice

| | **Basic** | **Advanced** |
|---|---|---|
| Extra software | **none** | an MQTT broker + Home Assistant |
| You get | a live web page | HA dashboards, history, automations |
| How | open `http://<machine-ip>:8080` | your HA dashboards |

They're independent switches — run **either or both** at the same time. The web dashboard is **on by
default**; MQTT is opt-in.

## Quick start — Docker (recommended)

The turnkey path: no Python, no venv.

```bash
git clone <this-repo> open-murata-bms && cd open-murata-bms
cp config/config.example.yaml config.yaml     # edit: your serial port / gateway, module ids
docker compose up -d
# then open  http://<this-machine-ip>:8080
```

Edit `docker-compose.yml` to map your USB-RS485 adapter (find it with `ls -l /dev/serial/by-id/`),
or skip that block if you use a TCP gateway (EW11 / Waveshare). To also feed Home Assistant, set
`integration.mqtt.enabled: true` in `config.yaml`.

## Quick start — from source (Raspberry Pi or any Linux/Mac)

```bash
python3 -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install .
cp config/config.example.yaml config.yaml            # edit for your install
omb --config config.yaml --once --dry-run            # verify it reads your modules (no MQTT)
omb --config config.yaml                              # run for real -> http://<ip>:8080
```

To run it as a boot service on a Pi, see [`packaging/omb.service`](packaging/omb.service). For
full-speed polling on FTDI/PL2303 adapters, install
[`packaging/99-ftdi-latency.rules`](packaging/99-ftdi-latency.rules).

## For developers (no hardware needed)

```bash
pip install -e ".[dev]"
pytest                                               # runs against the simulator; no hardware
```

## License

[MIT](LICENSE).

## Documentation

- **[Complete Beginner Guide](docs/GETTING-STARTED.md)** — zero to a live dashboard.
- **[Register map & encoding](docs/REGISTER-MAP.md)** — the full 125-register map, data types, and
  alarm/warning bit definitions.
- **[Module hardware](docs/hardware/murata-module.md)** — pinout, ID switches, LEDs, wiring.
- **[Home Assistant + MQTT](docs/HOME-ASSISTANT.md)** — optional: run Mosquitto (and HA) on the Pi.

## Vendor material

Original hardware/software docs live in [`docs/`](docs/). **Vendor manuals are copyrighted and are
never committed** — they stay in git-ignored locations. This project documents the concepts in its
own words.
