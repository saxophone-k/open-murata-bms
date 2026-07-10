"""Module driver tests — the whole read+decode+scale stack, run against the simulator transport."""

from omb.drivers.module_reader import ModuleReading, poll_modules, read_module
from omb.sim.module import SimBank
from omb.transport.sim import SimTransport


def test_read_module_scales_to_engineering_units():
    t = SimTransport(SimBank.of(count=4))
    r = read_module(t, 2)
    assert isinstance(r, ModuleReading)
    assert r.unit == 2
    assert r.vendor_name == "SONY" and r.product_code == "IJ1101M"
    assert r.software_version == "01.02.00"
    assert r.soc_pct == 82.0 and r.soh_pct == 94.0 and r.cycle_count == 459
    assert round(r.voltage_v, 3) == 52.452
    assert len(r.cell_voltages_v) == 16 and len(r.cell_temps_c) == 8
    assert min(r.cell_voltages_v) == 3.276 and max(r.cell_voltages_v) == 3.280
    assert 10 < r.max_cell_temp_c < 20              # ~14.75 °C
    assert not r.has_alarm                          # healthy module: no active alarms
    assert r.charge_fet_on and r.discharge_fet_on
    assert r.config["cell_count"] == 16


def test_faulted_module_reports_low_voltage_and_open_fets():
    t = SimTransport(SimBank.of(count=18, faulted_ids=(1,)))
    r = read_module(t, 1)
    assert "low_voltage" in r.alarms and r.has_alarm
    assert not r.charge_fet_on and not r.discharge_fet_on   # module isolated itself


def test_absent_module_returns_none():
    t = SimTransport(SimBank.of(count=4))
    assert read_module(t, 99) is None


def test_poll_modules_returns_only_present():
    t = SimTransport(SimBank.of(count=18, faulted_ids=(1,)))
    readings = poll_modules(t, range(1, 25))     # ask 1..24; only 1..18 exist
    assert set(readings) == set(range(1, 19))
    assert readings[1].has_alarm and not readings[2].has_alarm


def test_cell_imbalance_helper():
    r = read_module(SimTransport(SimBank.of(count=2)), 1)
    assert r.cell_imbalance_mv == 4.0             # 3.280 - 3.276 V
