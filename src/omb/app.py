"""open-murata-bms application loop — poll the ESS and publish to MQTT / Home Assistant.

This is the clean, config-driven successor to a hand-written poll script: it reads the config, opens a
transport per bank (USB serial, or RTU-over-TCP through a gateway), and every `poll.interval_s` polls
every module, rolls the readings up to bank + ESS, and publishes to the broker with HA discovery.

Run:  python -m omb --config config/config.yaml   [--once]
Read-only: it never issues a Modbus write (dangerous writes live behind `safety`, off by default).
"""

from __future__ import annotations

import argparse
import logging
import time

from omb.config import load_config
from omb.integration.mqtt import MqttPublisher
from omb.integration.webdash import WebDashboard
from omb.model.aggregate import poll_ess
from omb.transport.live import ModbusTransport

log = logging.getLogger("omb")


def build_banks(config) -> dict[str, tuple]:
    """Open one transport per configured bank. Returns {bank_id: (transport, unit_ids)}."""
    banks: dict[str, tuple] = {}
    for b in config.banks:
        tp = ModbusTransport(b.transport, timeout_s=b.timeout_ms / 1000, retries=b.retries)
        if not tp.connect():
            log.warning("bank %s: transport did not connect (will keep trying on poll)", b.id)
        banks[b.id] = (tp, b.module_ids())
    return banks


def _print_ess(ess, total_modules: int) -> None:
    """Human-readable rollup for --dry-run: verify wiring/config before touching MQTT."""
    flag = "  *** ALARM ***" if ess.has_alarm else ""
    print(f"\nESS '{ess.name}'  —  {ess.module_count}/{total_modules} modules answered"
          f"  |  {ess.voltage_v:.1f} V  {ess.current_a:+.1f} A  SOC {ess.soc_pct:.0f}%{flag}")
    for bank in ess.banks.values():
        bflag = "  *** ALARM ***" if bank.has_alarm else ""
        print(f"  {bank.name}  [{bank.bank_id}]  —  {len(bank.modules)}/{bank.expected} modules"
              f"  |  {bank.voltage_v:.1f} V  {bank.current_a:+.1f} A  SOC {bank.soc_pct:.0f}%{bflag}")
        for uid, m in bank.modules.items():
            mflag = "  ALARM: " + ", ".join(m.alarms) if m.has_alarm else ""
            print(f"      module {uid:>2}  {m.voltage_v:6.2f} V  {m.current_a:+7.1f} A"
                  f"  SOC {m.soc_pct:5.1f}%  SOH {m.soh_pct:3.0f}%"
                  f"  cell {m.min_cell_voltage_v:.3f}/{m.max_cell_voltage_v:.3f} V (Δ{m.cell_imbalance_mv:.0f} mV)"
                  f"  {m.min_cell_temp_c:.0f}–{m.max_cell_temp_c:.0f} °C{mflag}")
    if not ess.module_count:
        print("  (no modules answered — check the serial port, wiring, and slave-id range)")


def run(config_path: str, once: bool = False, dry_run: bool = False) -> None:
    config = load_config(config_path)
    log.info("ESS '%s': %d bank(s), %d modules configured",
             config.ess.name, len(config.banks), config.total_modules())
    banks = build_banks(config)
    names = {b.id: (b.name or b.id) for b in config.banks}

    pub = None
    web = None
    if not dry_run:
        if config.integration.mqtt.enabled:
            pub = MqttPublisher(config.integration.mqtt)
            pub.connect()
            log.info("connected to MQTT %s:%d", config.integration.mqtt.host, config.integration.mqtt.port)
        if config.integration.web.enabled:
            web = WebDashboard(config.integration.web.host, config.integration.web.port)
            web.start()
        if pub is None and web is None:
            log.warning("no integration enabled (mqtt + web both off) — polling only")
    else:
        log.info("dry-run: polling only, MQTT/web disabled")

    discovered_ids: set[tuple[str, int]] = set()
    try:
        while True:
            # A long-running service must survive any single bad cycle (bus glitch, broker
            # blip). Log it and keep going; never let one exception end the loop.
            try:
                ess = poll_ess(banks, names=names, ess_name=config.ess.name)
                if pub is not None:
                    # (Re)publish discovery whenever a module we haven't announced appears — so a
                    # partial first poll, or a module that comes online later, still gets HA entities.
                    seen = {(bid, uid) for bid, bank in ess.banks.items() for uid in bank.modules}
                    if seen - discovered_ids:
                        pub.publish_discovery(ess)   # retained + idempotent — safe to re-send
                        discovered_ids |= seen
                        log.info("published HA discovery (%d modules known)", len(discovered_ids))
                    pub.publish_states(ess)
                if web is not None:
                    web.update(ess)
                if dry_run:
                    _print_ess(ess, config.total_modules())
                else:
                    log.info("polled %d/%d modules  %.1fV %+.1fA  SOC %.0f%%%s",
                             ess.module_count, config.total_modules(), ess.voltage_v, ess.current_a,
                             ess.soc_pct, "  ALARM" if ess.has_alarm else "")
            except Exception:
                log.exception("poll cycle failed; continuing")
            if once:
                break
            time.sleep(config.poll.interval_s)
    finally:
        if pub is not None:
            pub.close()
        if web is not None:
            web.close()
        for tp, _ in banks.values():
            tp.close()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="open-murata-bms — poll modules and publish to MQTT/HA")
    p.add_argument("--config", default="config/config.yaml", help="path to config.yaml")
    p.add_argument("--once", action="store_true", help="poll once and exit (for testing)")
    p.add_argument("--dry-run", action="store_true",
                   help="poll and print the rollup; do not connect to MQTT (verify wiring/config)")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args(argv)
    logging.basicConfig(level=args.log_level,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run(args.config, once=args.once, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
