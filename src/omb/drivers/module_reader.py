"""Murata module driver — read a module through any Transport and produce a clean `ModuleReading`.

This is the "heartbeat": ask the transport for the full 125-register block, decode it (via the
register map + codec), and scale everything into human engineering units (volts, amps, °C, %),
including the per-cell arrays and named alarms/warnings. Read-only; a silent module → `None`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from omb.drivers.murata_module import FULL_READ_WORDS, decode_block, decode_cells

# module_alarm / module_warning bit meanings (from the comm spec)
_ALARM_BITS = {
    0: "over_voltage", 1: "over_charge_current", 2: "over_discharge_current",
    3: "over_temp_charge", 4: "over_temp_discharge", 5: "under_temp_charge",
    6: "under_temp_discharge", 28: "low_voltage", 31: "cell_unbalance",
}
_WARNING_BITS = {
    1: "over_charge_discharge_current", 2: "cell_balancing",
    16: "afe_data_freeze", 17: "afe_data_outlier",
}


def _active(value: int, table: dict[int, str]) -> list[str]:
    return [name for bit, name in table.items() if (value >> bit) & 1]


def _ver(s: str) -> str:
    return f"{s[:2]}.{s[2:4]}.{s[4:6]}" if len(s) >= 6 else s


def _c_from_dk(dk: int) -> float:
    """0.1 K -> °C."""
    return round(dk / 10 - 273.15, 2)


@dataclass(frozen=True)
class ModuleReading:
    unit: int | None
    # identity
    product_code: str
    vendor_name: str
    destination_code: str
    serial_number: int
    software_version: str
    protocol_version: str
    manufacture_date: date
    # state of charge / health
    soc_pct: float
    soh_pct: float
    cycle_count: int
    # electrical
    voltage_v: float
    current_a: float
    average_current_a: float
    max_cell_voltage_v: float
    min_cell_voltage_v: float
    max_cell_temp_c: float
    min_cell_temp_c: float
    remaining_capacity_ah: float
    full_charge_capacity_ah: float
    charge_current_limit_a: float
    discharge_current_limit_a: float
    # per-cell detail
    cell_voltages_v: list[float]
    cell_temps_c: list[float]
    # switches / status
    charge_fet_on: bool
    discharge_fet_on: bool
    system_ready: bool
    # health flags (active only)
    alarms: list[str]
    warnings: list[str]
    # static nameplate (meaning tentative — see murata_module.BATTERY_INFO)
    config: dict = field(default_factory=dict)
    raw: list[int] = field(default_factory=list)

    @property
    def has_alarm(self) -> bool:
        return bool(self.alarms)

    @property
    def has_warning(self) -> bool:
        return bool(self.warnings)

    @property
    def cell_imbalance_mv(self) -> float:
        return round((self.max_cell_voltage_v - self.min_cell_voltage_v) * 1000, 1)


def interpret(regs: list[int], unit: int | None = None) -> ModuleReading:
    """Decode a full 125-register block into a scaled ModuleReading."""
    d = decode_block(regs)
    cells = decode_cells(regs)
    cds = d["charge_discharge_status"]
    return ModuleReading(
        unit=unit,
        product_code=d["product_code"], vendor_name=d["vendor_name"],
        destination_code=d["destination_code"], serial_number=d["serial_number"],
        software_version=_ver(d["software_version"]), protocol_version=_ver(d["protocol_version"]),
        manufacture_date=d["manufacture_date"],
        soc_pct=d["rsoc"] / 10, soh_pct=d["soh"] / 10, cycle_count=d["cycle_count"],
        voltage_v=d["dc_voltage"] / 1000,
        current_a=d["current"] / 1000, average_current_a=d["average_current"] / 1000,
        max_cell_voltage_v=d["max_cell_voltage"] / 1000, min_cell_voltage_v=d["min_cell_voltage"] / 1000,
        max_cell_temp_c=_c_from_dk(d["max_cell_temp"]), min_cell_temp_c=_c_from_dk(d["min_cell_temp"]),
        remaining_capacity_ah=d["remaining_capacity"] / 1000,
        full_charge_capacity_ah=d["full_charge_capacity"] / 1000,
        charge_current_limit_a=d["charge_current_limit"] / 1000,
        discharge_current_limit_a=d["discharge_current_limit"] / 1000,
        cell_voltages_v=[v / 1000 for v in cells["cell_voltages_mv"]],
        cell_temps_c=[_c_from_dk(t) for t in cells["cell_temps_dk"]],
        charge_fet_on=(cds & 0xFF) == 0, discharge_fet_on=((cds >> 8) & 0xFF) == 0,
        system_ready=bool(d["module_status"] & 1),
        alarms=_active(d["module_alarm"], _ALARM_BITS),
        warnings=_active(d["module_warning"], _WARNING_BITS),
        config={
            "nominal_voltage_v": d["info_nominal_voltage"] / 1000,
            "capacity_ah": d["info_capacity"] / 1000,
            "cell_count": d["info_cell_count"],
        },
        raw=list(regs),
    )


def read_module(transport, unit: int) -> ModuleReading | None:
    """Poll one module through `transport`. Returns None if it doesn't answer (absent/timeout)."""
    regs = transport.read_input_registers(unit, 0x0000, FULL_READ_WORDS)
    if regs is None or len(regs) < FULL_READ_WORDS:
        return None
    return interpret(regs, unit=unit)


def poll_modules(transport, unit_ids) -> dict[int, ModuleReading]:
    """Poll a set of module ids on one link; returns only the ones that answered (keyed by id)."""
    out: dict[int, ModuleReading] = {}
    for uid in unit_ids:
        r = read_module(transport, uid)
        if r is not None:
            out[uid] = r
    return out
