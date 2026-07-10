# Murata IJ1101M — register map & encoding

This is the register map **open-murata-bms** implements, verified against real hardware (a
BAT2-EBAT-18 cabinet, 2026-07). It is our own reverse-engineered data model — not a reproduction of
Murata's copyrighted specification. Addresses are **0-based input-register offsets**.

## How to read a module

- **Function:** Modbus **FC 0x04 (Read Input Registers)**. A module answers reads; it is polled, it
  does not initiate.
- **Serial:** 230400 baud, 8 data bits, **Even** parity, 1 stop bit. Recommended master timeout
  ~25 ms, retry on timeout. An absent ID simply stays silent (not an error).
- **A full read** is FC 0x04 at address `0x0000`, count **125** registers (`0x0000`–`0x007C`). The
  named fields below occupy `0x0000`–`0x004A`; `0x005D`+ holds per-cell data (see the last table).

## Encoding conventions

| Type | Size | Encoding |
|------|------|----------|
| `UINT16` | 1 register | unsigned, big-endian |
| `UINT32` / `SINT32` | 2 registers | **high word first** (big-endian across both registers) |
| `ASCII` | N registers | **byte-swapped** — the two bytes in each register are swapped, so `"MURA"` arrives as `"UMAR"`. Decode by un-swapping each register's byte pair. |
| `DATE` | 1 register | bit-packed: **bits 15–9** = 2000 + YY, **bits 8–5** = month, **bits 4–0** = day |
| `bitfield` | 1–2 registers | individual status/alarm/warning bits (see bit tables) |
| temperature | 1 register | units of **0.1 K**; °C = raw × 0.1 − 273.15 |

Scaled values below use `engineering = raw × scale` (e.g. a `0.001 V` field of `52640` = 52.640 V).

## Device information — `0x0000`–`0x0012`

| Offset | Registers | Name | Type | Notes |
|-------:|:---------:|------|------|-------|
| `0x0000` | 3 | protocol_version | ASCII | e.g. `010010` → 01.00.10 |
| `0x0003` | 4 | product_code | ASCII | `"IJ1101M"` |
| `0x0007` | 2 | destination_code | ASCII | e.g. `"ESW"` |
| `0x0009` | 1 | system_version | ASCII | |
| `0x000A` | 1 | electrical_version | ASCII | |
| `0x000B` | 3 | software_version | ASCII | e.g. `010200` → 01.02.00 |
| `0x000E` | 2 | vendor_name | ASCII | `"SONY"` on pre-Murata units, else `"MURA"` |
| `0x0010` | 1 | manufacture_date | DATE | packed year/month/day |
| `0x0011` | 2 | serial_number | UINT32 | |

## Battery information — `0x0013`–`0x0024`

> ⚠️ **Meanings here are unconfirmed hypotheses.** These values are identical across all modules we
> tested (factory-set/uniform), but whether a field is a *design nominal*, a *protection limit*, or a
> *warranty reference* is **not established**. **Do not use these as protection limits** without
> confirming their meaning. Field names are deliberately neutral.

| Offset | Registers | Name | Type | Scale | Observed | Notes |
|-------:|:---------:|------|------|:-----:|----------|-------|
| `0x0013` | 2 | info_nominal_voltage | UINT32 | 0.001 V | 51.2 V | 16 × 3.2 V; likely nominal |
| `0x0015` | 2 | info_capacity | UINT32 | 0.001 Ah | 42.0 Ah | matches the tech sheet |
| `0x001C` | 1 | info_cell_count | UINT16 | — | 16 | structural, high confidence |
| `0x001D` | 2 | info_voltage_hi | UINT32 | 0.001 V | 56.0 V | charge limit **or** max-recorded? unconfirmed |
| `0x001F` | 2 | info_voltage_lo | UINT32 | 0.001 V | 36.8 V | discharge limit **or** min-recorded? unconfirmed |
| `0x0021` | 2 | info_current_a | UINT32 | 0.001 A | 40 A | rated **or** max-recorded? unconfirmed |
| `0x0023` | 2 | info_current_b | UINT32 | 0.001 A | 40 A | rated **or** max-recorded? unconfirmed |

*(`0x0025`–`0x002B` differ per module — lot/serial/date metadata — and are left undecoded.)*

## Battery status (live) — `0x002C`–`0x004A`

| Offset | Registers | Name | Type | Scale | Notes |
|-------:|:---------:|------|------|:-----:|-------|
| `0x002C` | 2 | system_time | UINT32 | 1 s | module uptime/clock |
| `0x002E` | 2 | module_status | bitfield | — | see status bits |
| `0x0030` | 2 | module_alarm | bitfield | — | see alarm bits |
| `0x0032` | 2 | module_warning | bitfield | — | see warning bits |
| `0x0034` | 1 | charge_discharge_status | bitfield | — | high byte = discharge FET, low byte = charge FET; **0 = ON, 2 = OFF** |
| `0x0035` | 2 | charge_current_limit | UINT32 | 0.001 A | |
| `0x0037` | 2 | discharge_current_limit | UINT32 | 0.001 A | |
| `0x0039` | 2 | current | **SINT32** | 0.001 A | + = charging, − = discharging |
| `0x003B` | 2 | average_current | SINT32 | 0.001 A | |
| `0x003D` | 2 | dc_voltage | UINT32 | 0.001 V | pack terminal voltage |
| `0x003F` | 1 | max_cell_voltage | UINT16 | 0.001 V | |
| `0x0040` | 1 | min_cell_voltage | UINT16 | 0.001 V | |
| `0x0041` | 1 | max_cell_temp | UINT16 | 0.1 K | °C = raw × 0.1 − 273.15 |
| `0x0042` | 1 | min_cell_temp | UINT16 | 0.1 K | |
| `0x0043` | 1 | rsoc | UINT16 | 0.1 % | state of charge |
| `0x0044` | 2 | remaining_capacity | UINT32 | 0.001 Ah | |
| `0x0046` | 2 | full_charge_capacity | UINT32 | 0.001 Ah | |
| `0x0048` | 1 | soh | UINT16 | 0.1 % | state of health |
| `0x0049` | 1 | cycle_count | UINT16 | — | charge cycles |

> The `0x34`–`0x38` region is mis-tabulated in the public PDF and the earlier ChatGPT poller decoded
> it wrong (charge-current-limit came out as ~2.75 million A). The layout above is the corrected one —
> the only one consistent with the field sizes **and** with `current` landing at `0x39`, confirmed on
> real modules.

## Per-cell block — `0x005D`–`0x0074` (full 125-register read only)

| Offset | Count | Name | Type | Notes |
|-------:|:-----:|------|------|-------|
| `0x005D`–`0x006C` | 16 | cell voltages | UINT16 | one per cell, **mV** |
| `0x006D`–`0x0074` | 8 | cell temperatures | UINT16 | one per sensor, **0.1 K** |

*(`0x004B`–`0x005C` are returned but not yet decoded.)*

## Bit definitions

**`module_alarm` (`0x0030`)** — a protective condition:

| Bit | Meaning | | Bit | Meaning |
|----:|---------|-|----:|---------|
| 0 | over_voltage | | 5 | under_temp_charge |
| 1 | over_charge_current | | 6 | under_temp_discharge |
| 2 | over_discharge_current | | 28 | low_voltage |
| 3 | over_temp_charge | | 31 | cell_unbalance |
| 4 | over_temp_discharge | | | |

**`module_warning` (`0x0032`)** — advisory, not yet protective:

| Bit | Meaning |
|----:|---------|
| 1 | over_charge_discharge_current |
| 2 | cell_balancing |
| 16 | afe_data_freeze |
| 17 | afe_data_outlier |

**`charge_discharge_status` (`0x0034`)** — high byte = discharge FET, low byte = charge FET; `0` = ON,
`2` = OFF.

---

*Remember: these are **read** registers (FC 0x04). Any register **write** to a module is a dangerous,
guarded operation — see [`SAFETY.md`](../SAFETY.md).*
