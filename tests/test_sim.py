"""Simulator tests — a fake module must answer polls exactly like the documented/real layout."""

import pytest

from omb import modbus
from omb.drivers.murata_module import decode_block
from omb.sim.module import ModuleState, SimBank, SimModule


def test_healthy_module_roundtrips_through_register_map():
    mod = SimModule(ModuleState())
    regs = mod.read_input_registers(0x0000, 75)
    assert regs is not None and len(regs) == 75
    d = decode_block(regs)
    assert d["vendor_name"] == "SONY"
    assert d["product_code"] == "IJ1101M"
    assert d["destination_code"] == "ESW"
    assert d["serial_number"] == 3000197
    assert d["dc_voltage"] == 52452          # mV
    assert d["rsoc"] == 820                  # 0.1 %
    assert d["cycle_count"] == 459
    assert d["module_alarm"] == 0            # healthy: no alarms


def test_charge_current_limit_decodes_sanely_not_the_old_bug():
    # The prior poller read ~2.75M A here; correct value is 42 A.
    regs = SimModule(ModuleState()).read_input_registers(0x0000, 75)
    d = decode_block(regs)
    assert d["charge_current_limit"] == 42000       # mA
    assert d["discharge_current_limit"] == 60000    # mA


def test_faulted_module_reports_low_voltage_alarm():
    mod = SimModule(ModuleState.faulted())
    d = decode_block(mod.read_input_registers(0x0000, 75))
    assert (d["module_alarm"] >> 28) & 1 == 1        # Low Voltage
    # FET status: hi byte DIS, lo byte CHG; both OFF (==2) on the faulted module
    assert (d["charge_discharge_status"] >> 8) & 0xFF == 2
    assert d["charge_discharge_status"] & 0xFF == 2


def test_out_of_range_read_is_silent():
    mod = SimModule(ModuleState())
    assert mod.read_input_registers(0x0100, 2) is None   # like real hardware: no response


def test_bank_addressing_and_absent_slave():
    bank = SimBank.of(count=18, faulted_ids=(1,))
    assert bank.read_input_registers(19, 0x0000, 75) is None   # absent slave -> silent
    d1 = decode_block(bank.read_input_registers(1, 0x0000, 75))
    d2 = decode_block(bank.read_input_registers(2, 0x0000, 75))
    assert (d1["module_alarm"] >> 28) & 1 == 1     # module 1 faulted
    assert d2["module_alarm"] == 0                 # module 2 healthy
    assert d1["serial_number"] == 3000001 and d2["serial_number"] == 3000002


# ── write path / fault-clear dry-run ─────────────────────────────────────────

def test_bare_module_rejects_writes_and_fc03():
    """The pessimistic hypothesis: a bare module answers only FC 0x04 reads."""
    mod = SimModule(ModuleState())            # defaults: accepts_writes=False, implements_fc03=False
    with pytest.raises(modbus.ModbusException) as e1:
        mod.write_single(modbus.RESET_ALARM_LOCK, 1)
    assert e1.value.code == modbus.ILLEGAL_FUNCTION
    with pytest.raises(modbus.ModbusException):
        mod.read_holding(0x0006, 1)           # safe FC03 probe also refused


def test_fault_clear_clears_overcurrent_lock_on_bmu_like_device():
    state = ModuleState()
    state.module_alarm = (1 << 2) | (1 << 28)     # over-discharge-current + low-voltage
    mod = SimModule(state, accepts_writes=True)
    mod.write_single(modbus.RESET_ALARM_LOCK, 1)  # the decoded fault-clear
    assert (mod.state.module_alarm >> 2) & 1 == 0    # over-current lock cleared
    assert (mod.state.module_alarm >> 28) & 1 == 1   # low-voltage NOT cleared (per manual)


def test_fault_clear_does_not_revive_uv_latched_module():
    # Module 1's real state: only the Low-Voltage latch. Alarm Lock Reset must leave it latched.
    mod = SimModule(ModuleState.faulted(), accepts_writes=True)
    before = mod.state.module_alarm
    mod.write_single(modbus.RESET_ALARM_LOCK, 1)
    assert mod.state.module_alarm == before == 0x10000000


def test_fault_clear_rejects_bad_value():
    mod = SimModule(ModuleState(), accepts_writes=True)
    with pytest.raises(modbus.ModbusException) as e:
        mod.write_single(modbus.RESET_ALARM_LOCK, 5)   # only value 1 is allowed
    assert e.value.code == modbus.ILLEGAL_DATA_VALUE


def test_fc03_probe_works_when_device_implements_it():
    mod = SimModule(ModuleState(), accepts_writes=True, implements_fc03=True)
    mod.write_single(0x0065, 0x555)                    # Operation Setting
    assert mod.read_holding(0x0065, 1) == [0x555]


def test_full_read_exposes_per_cell_voltages_and_temps():
    from omb.drivers.murata_module import decode_cells
    regs = SimModule(ModuleState()).read_input_registers(0x0000, 125)   # the BMU's full read
    assert regs is not None and len(regs) == 125
    cells = decode_cells(regs)
    assert len(cells["cell_voltages_mv"]) == 16          # 16 cells
    assert len(cells["cell_temps_dk"]) == 8              # 8 temp sensors
    # cells spread between the module's min/max cell voltage (3276..3280 mV by default)
    assert min(cells["cell_voltages_mv"]) == 3276
    assert max(cells["cell_voltages_mv"]) == 3280


def test_bank_write_to_absent_slave_is_silent():
    bank = SimBank.of(count=18)
    assert bank.write_single(99, modbus.RESET_ALARM_LOCK, 1) is None   # timeout, not exception
