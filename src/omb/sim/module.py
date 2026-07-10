"""Murata module simulator — a faithful protocol stand-in (not a cell/physics model).

Values are stored in RAW register units (mV, mA, 0.1 K, 0.1 %, mAh, seconds) so encoding is an exact
round-trip with what a real module reports. Defaults are seeded from a real BAT2-EBAT-18 cabinet
(2026-07). `ModuleState.faulted()` reproduces the actual under-voltage/permanent-failure module
(module 1) observed on that bench: Low-Voltage alarm bit, undocumented status nibble, FETs OFF.

Real-hardware behaviors reproduced by SimModule:
- a read whose range steps outside the implemented map returns **no response** (None) — real modules
  stay silent rather than sending an ILLEGAL DATA ADDRESS exception.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from omb import codec, modbus
from omb.drivers.murata_module import (
    BY_NAME,
    CELL_COUNT,
    CELL_TEMP_BASE,
    CELL_VOLTAGE_BASE,
    FULL_READ_WORDS,
    TEMP_SENSOR_COUNT,
)

# module_alarm bit positions (from the comm spec)
_ALARM_OVER_CHARGE_CURRENT = 1
_ALARM_OVER_DISCHARGE_CURRENT = 2
_ALARM_LOW_VOLTAGE = 28

# Captured undocumented "Battery Information" block (0x13..0x2B) from a real module — kept so the
# simulator answers those addresses realistically too (config: ~56 V / 40 A / ~42 Ah / 16 cells).
_BATTERY_INFO_FILLER: dict[int, int] = {
    0x13: 0x0000, 0x14: 0xC800, 0x15: 0x0000, 0x16: 0xA410, 0x17: 0x0000, 0x18: 0x0000,
    0x19: 0x0000, 0x1A: 0x0000, 0x1B: 0x000E, 0x1C: 0x0010, 0x1D: 0x0000, 0x1E: 0xDAC0,
    0x1F: 0x0000, 0x20: 0x8FC0, 0x21: 0x0000, 0x22: 0x9C40, 0x23: 0x0000, 0x24: 0x9C40,
    0x25: 0x55F2, 0x26: 0x05CD, 0x27: 0xC094, 0x28: 0x1E87, 0x29: 0xB8AE, 0x2A: 0x1F96,
    0x2B: 0x55F1,
}


@dataclass
class ModuleState:
    # Device info
    protocol_version: str = "010010"
    product_code: str = "IJ1101M"
    destination_code: str = "ESW"
    system_version: str = "01"
    electrical_version: str = "01"
    software_version: str = "010200"
    vendor_name: str = "SONY"           # real pre-Murata firmware; use "MURA" for newer units
    manufacture_date: date = date(2015, 12, 22)
    serial_number: int = 3000197

    # Battery Information block (identical on all real modules; MEANINGS unconfirmed — see
    # murata_module.BATTERY_INFO. Neutral names on purpose; do not treat as protection limits.)
    info_nominal_voltage: int = 51200       # mV (=51.2 V)
    info_capacity: int = 42000              # mAh (=42.0 Ah)
    info_cell_count: int = 16
    info_voltage_hi: int = 56000            # mV (=56.0 V)
    info_voltage_lo: int = 36800            # mV (=36.8 V)
    info_current_a: int = 40000             # mA (=40 A)
    info_current_b: int = 40000             # mA (=40 A)

    # Status / alarm / warning (raw bitfields) — healthy defaults from modules 2..18
    system_time: int = 156_549_600      # seconds
    module_status: int = 0x03230009     # Normal, System Ready
    module_alarm: int = 0x00000000
    module_warning: int = 0x00000001
    charge_discharge_status: int = 0x0000   # both FETs ON

    # Electrical (raw units)
    charge_current_limit: int = 42000       # mA
    discharge_current_limit: int = 60000    # mA
    current: int = -126                     # mA (signed)
    average_current: int = -123             # mA
    dc_voltage: int = 52452                 # mV
    max_cell_voltage: int = 3280            # mV
    min_cell_voltage: int = 3276            # mV
    max_cell_temp: int = 2879               # 0.1 K  -> 14.75 degC
    min_cell_temp: int = 2874               # 0.1 K  -> 14.25 degC
    rsoc: int = 820                         # 0.1 %  -> 82.0 %
    remaining_capacity: int = 31522         # mAh
    full_charge_capacity: int = 38556       # mAh
    soh: int = 940                          # 0.1 %  -> 94.0 %
    cycle_count: int = 459

    @classmethod
    def faulted(cls) -> ModuleState:
        """The real under-voltage / permanent-failure module (observed module 1)."""
        return cls(
            module_status=0x0028000F,        # current-status nibble = 8 (undocumented fault state)
            module_alarm=0x10000000,         # bit 28 = Low Voltage
            charge_discharge_status=0x0202,  # both FETs OFF (module isolated itself)
            current=1, average_current=1,
            dc_voltage=52658, max_cell_voltage=3292, min_cell_voltage=3290,
            rsoc=770,
        )

    def to_input_registers(self) -> list[int]:
        """Encode the full 125-word input-register block exactly as a real module answers (the count
        a full read returns), including the per-cell voltage/temperature block at 0x5D/0x6D."""
        regs = [0] * FULL_READ_WORDS
        for off, val in _BATTERY_INFO_FILLER.items():
            regs[off] = val
        regs[0x5B] = self.full_charge_capacity & 0xFFFF   # capacity echo seen on real hardware
        # per-cell voltages: spread evenly between min and max cell voltage
        span = self.max_cell_voltage - self.min_cell_voltage
        for i in range(CELL_COUNT):
            frac = i / (CELL_COUNT - 1) if CELL_COUNT > 1 else 0
            regs[CELL_VOLTAGE_BASE + i] = round(self.min_cell_voltage + frac * span)
        tspan = self.max_cell_temp - self.min_cell_temp
        for i in range(TEMP_SENSOR_COUNT):
            frac = i / (TEMP_SENSOR_COUNT - 1) if TEMP_SENSOR_COUNT > 1 else 0
            regs[CELL_TEMP_BASE + i] = round(self.min_cell_temp + frac * tspan)
        for name, f in BY_NAME.items():
            value = getattr(self, name)
            if f.kind == "ascii":
                words = codec.encode_ascii(value, f.words)
            elif f.kind in ("uint", "bitfield"):
                words = codec.encode_uint(value, f.words)
            elif f.kind == "sint":
                words = codec.encode_sint(value, f.words)
            elif f.kind == "date":
                words = codec.encode_date(value)
            else:  # pragma: no cover
                raise ValueError(f.kind)
            regs[f.offset : f.offset + f.words] = words
        return regs


class SimModule:
    """One simulated device answering Modbus for a given slave id.

    A bare **module** (defaults) answers only FC 0x04 reads and rejects writes / FC 0x03 — the
    pessimistic hypothesis that a bare module doesn't accept holding/maintenance writes. Set
    `accepts_writes=True` (and optionally `implements_fc03=True`) to model a **write-accepting
    controller** so we can dry-run the maintenance commands. Semantics follow Murata's manual: Alarm Lock
    Reset clears **over-current** locks only — a low-voltage / permanent-failure latch does NOT clear.
    """

    def __init__(self, state: ModuleState | None = None, *,
                 accepts_writes: bool = False, implements_fc03: bool = False):
        self.state = state or ModuleState()
        self.accepts_writes = accepts_writes
        self.implements_fc03 = implements_fc03
        self.holding: dict[int, int] = {}

    def read_input_registers(self, address: int, count: int) -> list[int] | None:
        block = self.state.to_input_registers()
        end = address + count
        if address < 0 or end > len(block):
            return None  # real modules go silent on out-of-range reads
        return block[address:end]

    def read_holding(self, address: int, count: int) -> list[int]:
        """FC 0x03 — the safe probe of the write space. A bare module rejects it."""
        if not self.implements_fc03:
            raise modbus.ModbusException(modbus.ILLEGAL_FUNCTION)
        return [self.holding.get(address + i, 0) for i in range(count)]

    def write_single(self, address: int, value: int) -> None:
        """FC 0x06. DANGEROUS on real hardware. Bare module rejects; a write-accepting device acts."""
        if not self.accepts_writes:
            raise modbus.ModbusException(modbus.ILLEGAL_FUNCTION)
        self.holding[address] = value
        self._apply_command(address, value)

    def write_multiple(self, address: int, values: list[int]) -> None:
        """FC 0x10. DANGEROUS on real hardware."""
        if not self.accepts_writes:
            raise modbus.ModbusException(modbus.ILLEGAL_FUNCTION)
        for i, v in enumerate(values):
            self.holding[address + i] = v

    def _apply_command(self, address: int, value: int) -> None:
        if address == modbus.RESET_ALARM_LOCK:
            if value != 1:
                raise modbus.ModbusException(modbus.ILLEGAL_DATA_VALUE)
            # Manual: clears the LOCKED (over-current) alarms only; UV/permanent-failure persists.
            self.state.module_alarm &= ~(
                (1 << _ALARM_OVER_CHARGE_CURRENT) | (1 << _ALARM_OVER_DISCHARGE_CURRENT)
            )


class SimBank:
    """A set of simulated modules keyed by slave id (e.g. 1..18 for one bank)."""

    def __init__(self, modules: dict[int, SimModule]):
        self.modules = modules

    @classmethod
    def of(cls, count: int = 18, faulted_ids: tuple[int, ...] = ()) -> SimBank:
        mods = {}
        for uid in range(1, count + 1):
            state = ModuleState.faulted() if uid in faulted_ids else ModuleState()
            state.serial_number = 3000000 + uid
            mods[uid] = SimModule(state)
        return cls(mods)

    def read_input_registers(self, uid: int, address: int, count: int) -> list[int] | None:
        mod = self.modules.get(uid)
        if mod is None:
            return None  # absent slave -> no response
        return mod.read_input_registers(address, count)

    def read_holding(self, uid: int, address: int, count: int) -> list[int] | None:
        mod = self.modules.get(uid)
        return None if mod is None else mod.read_holding(address, count)

    def write_single(self, uid: int, address: int, value: int) -> bool | None:
        mod = self.modules.get(uid)
        if mod is None:
            return None  # absent slave -> no response (timeout)
        mod.write_single(address, value)
        return True
