"""Murata IJ1101M module — the input-register map (FC 0x04), self-describing.

Single source of truth shared by the simulator (encode) and the driver (decode). Offsets are
0-based input-register addresses; verified against real hardware (a BAT2-EBAT-18 cabinet, 2026-07).

NOTE on the 0x34-0x38 region: the public PDF table is internally inconsistent here, and the prior
ChatGPT poller mis-decoded it (charge-current-limit came out as ~2.75M A). The layout below is the
*correct* one — it is the only one consistent with field sizes AND with `Current` landing at 0x39,
confirmed on real modules:
    0x34 charge/discharge FET status (1w) | 0x35-36 charge-current-limit | 0x37-38 discharge-limit
"""

from __future__ import annotations

from dataclasses import dataclass

from omb import codec

INPUT_BLOCK_WORDS = 75  # a full read is FC04 @ 0x0000 count 75 (0x0000..0x004A)


@dataclass(frozen=True)
class Field:
    name: str
    offset: int          # 0-based input register offset
    words: int
    kind: str            # 'ascii' | 'uint' | 'sint' | 'bitfield' | 'date'
    scale: float = 1.0   # engineering = raw * scale (informational; codec handles raw<->int)
    unit: str = ""
    note: str = ""


# Device Information (0x0000..0x0012)
DEVICE_INFO: list[Field] = [
    Field("protocol_version", 0x0000, 3, "ascii", note="e.g. 010010 -> 01.00.10"),
    Field("product_code", 0x0003, 4, "ascii", note='"IJ1101M"'),
    Field("destination_code", 0x0007, 2, "ascii", note='"ESW"'),
    Field("system_version", 0x0009, 1, "ascii"),
    Field("electrical_version", 0x000A, 1, "ascii"),
    Field("software_version", 0x000B, 3, "ascii", note="e.g. 010200 -> 01.02.00"),
    Field("vendor_name", 0x000E, 2, "ascii", note='"SONY" on pre-Murata units, else "MURA"'),
    Field("manufacture_date", 0x0010, 1, "date"),
    Field("serial_number", 0x0011, 2, "uint"),
]

# Battery Information block (0x0013..0x0024) — NOT tabulated in the comm spec (only *named* in its
# overview). Reverse-engineered from real hardware.
#
#   VALUES are confirmed: identical across all 18 modules (0x0025..0x002B, which DO differ per module,
#   are lot/serial/date metadata, left undecoded). MEANINGS below are HYPOTHESES, not established:
#   the identical-across-modules fact argues these are factory-set/uniform (not per-module "lifetime
#   recorded max/min" warranty values, which would vary by usage like cycle_count does) — but whether
#   a field is a design nominal, a protection limit, or a warranty reference threshold is UNCONFIRMED.
#   *** Do NOT use these as protection limits anywhere without confirming their meaning first. ***
#   Names are deliberately NEUTRAL (voltage_hi/lo, current_a/b) so the code does not assert a meaning.
BATTERY_INFO: list[Field] = [
    Field("info_nominal_voltage", 0x0013, 2, "uint", 0.001, "V", note="=51.2 V (16 x 3.2 V); likely nominal"),
    Field("info_capacity", 0x0015, 2, "uint", 0.001, "Ah", note="=42.0 Ah; matches tech spec"),
    Field("info_cell_count", 0x001C, 1, "uint", note="=16; structural, high confidence"),
    Field("info_voltage_hi", 0x001D, 2, "uint", 0.001, "V", note="=56.0 V; charge limit OR max-recorded? UNCONFIRMED"),
    Field("info_voltage_lo", 0x001F, 2, "uint", 0.001, "V", note="=36.8 V; dischg limit OR min-recorded? UNCONFIRMED"),
    Field("info_current_a", 0x0021, 2, "uint", 0.001, "A", note="=40 A; rated OR max-recorded? UNCONFIRMED"),
    Field("info_current_b", 0x0023, 2, "uint", 0.001, "A", note="=40 A; rated OR max-recorded? UNCONFIRMED"),
]

# Battery Status Information (0x002C..0x004A)
BATTERY_STATUS: list[Field] = [
    Field("system_time", 0x002C, 2, "uint", 1, "s"),
    Field("module_status", 0x002E, 2, "bitfield"),
    Field("module_alarm", 0x0030, 2, "bitfield"),
    Field("module_warning", 0x0032, 2, "bitfield"),
    Field("charge_discharge_status", 0x0034, 1, "bitfield",
          note="hi byte DIS-FET, lo byte CHG-FET; 0=ON, 2=OFF"),
    Field("charge_current_limit", 0x0035, 2, "uint", 0.001, "A"),
    Field("discharge_current_limit", 0x0037, 2, "uint", 0.001, "A"),
    Field("current", 0x0039, 2, "sint", 0.001, "A"),
    Field("average_current", 0x003B, 2, "sint", 0.001, "A"),
    Field("dc_voltage", 0x003D, 2, "uint", 0.001, "V"),
    Field("max_cell_voltage", 0x003F, 1, "uint", 0.001, "V"),
    Field("min_cell_voltage", 0x0040, 1, "uint", 0.001, "V"),
    Field("max_cell_temp", 0x0041, 1, "uint", 0.1, "K", note="0.1 K; degC = raw*0.1 - 273.15"),
    Field("min_cell_temp", 0x0042, 1, "uint", 0.1, "K"),
    Field("rsoc", 0x0043, 1, "uint", 0.1, "%"),
    Field("remaining_capacity", 0x0044, 2, "uint", 0.001, "Ah"),
    Field("full_charge_capacity", 0x0046, 2, "uint", 0.001, "Ah"),
    Field("soh", 0x0048, 1, "uint", 0.1, "%"),
    Field("cycle_count", 0x0049, 1, "uint"),
]

REGISTER_MAP: list[Field] = DEVICE_INFO + BATTERY_INFO + BATTERY_STATUS
BY_NAME: dict[str, Field] = {f.name: f for f in REGISTER_MAP}

# Per-cell block — discovered from a full read (FC 0x04 count=125) observed on real hardware, 2026-07.
# The module actually returns 125 registers; 0x005D..0x0074 hold per-cell voltages then temperatures.
FULL_READ_WORDS = 125
CELL_VOLTAGE_BASE = 0x005D   # UINT16 mV, one per cell
CELL_COUNT = 16
CELL_TEMP_BASE = 0x006D      # UINT16 0.1 K, one per temperature sensor
TEMP_SENSOR_COUNT = 8


def decode_cells(regs: list[int]) -> dict:
    """Per-cell voltages [mV] and per-sensor temperatures [0.1 K] from a full (>=0x75) read block."""
    return {
        "cell_voltages_mv": [regs[CELL_VOLTAGE_BASE + i] for i in range(CELL_COUNT)],
        "cell_temps_dk": [regs[CELL_TEMP_BASE + i] for i in range(TEMP_SENSOR_COUNT)],
    }


def _decode_field(f: Field, regs: list[int]):
    chunk = regs[f.offset : f.offset + f.words]
    if f.kind == "ascii":
        return codec.decode_ascii(chunk)
    if f.kind == "uint" or f.kind == "bitfield":
        return codec.decode_uint(chunk)
    if f.kind == "sint":
        return codec.decode_sint(chunk)
    if f.kind == "date":
        return codec.decode_date(chunk)
    raise ValueError(f"unknown kind {f.kind}")


def decode_block(regs: list[int]) -> dict:
    """Decode a full 75-word input-register block into raw field values (no scaling)."""
    if len(regs) < INPUT_BLOCK_WORDS:
        raise ValueError(f"need {INPUT_BLOCK_WORDS} registers, got {len(regs)}")
    return {f.name: _decode_field(f, regs) for f in REGISTER_MAP}
