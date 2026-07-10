# Safety

**open-murata-bms talks to live, high-energy battery modules. Read this before you connect anything.**
You are responsible for your own hardware and safety. This software is provided "as is," with no
warranty (see [LICENSE](LICENSE)).

## 1. It monitors — it does **not** protect

This tool **reads** the modules and shows you their state, including alarms. **It does not act on those
alarms, and it cannot disconnect anything.** A Murata module raises a signal when something is wrong;
it does not open the circuit itself.

**You must provide your own disconnect strategy** — an inverter cut-off, a contactor/breaker you can
trip, or supervised manual disconnection during testing. Without one, a single unattended fault can
drain a module flat and permanently destroy it. This tool is your eyes, not your hands.

## 2. Read-only by default

Normal operation is **polling only** (Modbus FC 0x04, read input registers). Any code path that
**writes** a register, changes a mode, or actuates hardware is **dangerous**, is **disabled by default**
behind an explicit config flag, and should never be run against real hardware without a human
deliberately enabling it for that session.

## 3. Fault-clearing is dangerous, not a convenience

Clearing a latched fault can re-arm a module that the BMS disabled for a real protective reason
(over/under-voltage, over-temperature, imbalance, internal fault). **Never clear a fault without first
understanding *why* it latched**, and never do it automatically. On a parallel bank, a bad module can
dump into its healthy neighbors — retire a genuinely damaged module rather than resetting it.

## 4. When in doubt, stop

If you are unsure whether an action is safe, **don't do it.** "Ask first" beats "apologize after" on a
battery this size. High-voltage DC and large lithium banks can cause fire, equipment destruction, or
injury.

---

*Contributors: any feature that can write to a device must keep read and write paths cleanly
separated, keep writes off by default behind a config guard, and document the risk here.*
