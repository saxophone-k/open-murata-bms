# Architecture

open-murata-bms is built in clean layers so it scales from a single module to many, across one or
more RS-485 links, and can grow new device types and integrations without disturbing the rest.

## Layers

1. **Transport** — pluggable Modbus links: RS-485 serial (a USB adapter) and RTU-over-TCP (an
   Ethernet–RS-485 gateway). Everything above talks only through this seam, so adding a link type
   never touches driver code.
2. **Device drivers** — one per device *type*, self-describing its registers. The Murata IJ1101M
   module driver is the reference. Read paths and any (guarded) write paths are kept separate.
3. **Aggregation** — rolls readings up the hierarchy: **module → bank → ESS**. A *bank* is the set of
   modules on one RS-485 link; the *ESS* is all banks. Parallel modules sum current and capacity,
   share voltage, and surface the worst cell/temperature plus any alarms tagged with their location.
4. **Integration** — surfaces the data: a built-in, dependency-free **web dashboard** and/or **MQTT**
   with Home Assistant auto-discovery. Either or both can run at once.

## Principles

- **Config-driven.** Topology (banks, ids, transports), broker, and options come from one config
  file. Nothing install-specific is hardcoded.
- **Read-only by default.** Polling is safe; any register write is a separate, off-by-default,
  guarded path — see [SAFETY.md](SAFETY.md).
- **Runs locally.** The engine runs on a small always-on machine at the battery (e.g. a Raspberry
  Pi) and keeps working — including its local dashboard — even if the network, broker, or Home
  Assistant are down. It must not depend on an external server.
- **Encode the real limits.** For example, RS-485 allows 247 Modbus addresses but only ~32 unit
  loads per un-repeated segment — honor the documented per-bus module limit, not an assumption.
