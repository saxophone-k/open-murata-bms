"""Aggregation tests — module -> bank -> ESS rollup, and graceful collapse for small installs."""

from omb.model.aggregate import poll_bank, poll_ess
from omb.sim.module import SimBank
from omb.transport.sim import SimTransport


def test_bank_rollup():
    t = SimTransport(SimBank.of(count=18, faulted_ids=(1,)))
    bank = poll_bank(t, "bank1", range(1, 19))
    assert bank.bank_id == "bank1" and bank.present_count == 18 and bank.missing_count == 0
    assert 51 < bank.voltage_v < 53                    # parallel bus, ~mean of modules
    assert bank.current_a < 0                          # net discharge
    assert 650 < bank.full_charge_capacity_ah < 720    # 18 modules summed (~694 Ah)
    assert 75 < bank.soc_pct < 85
    assert bank.has_alarm and "module1: low_voltage" in bank.alarms


def test_missing_modules_counted():
    t = SimTransport(SimBank.of(count=18))
    bank = poll_bank(t, "b", range(1, 21))             # expect 20, only 18 answer
    assert bank.present_count == 18 and bank.missing_count == 2


def test_ess_rollup_multiple_banks():
    banks = {
        f"bank{i}": (
            SimTransport(SimBank.of(18, faulted_ids=(1,) if i == 1 else ())),
            range(1, 19),
        )
        for i in range(1, 5)
    }
    ess = poll_ess(banks)
    assert ess.bank_count == 4 and ess.module_count == 72
    assert 2700 < ess.full_charge_capacity_ah < 2850   # 72 modules summed
    assert ess.current_a < 0
    assert 75 < ess.soc_pct < 85
    assert ess.has_alarm and any("bank1/module1: low_voltage" in a for a in ess.alarms)
    assert not ess.banks["bank2"].has_alarm


def test_small_install_collapses_to_one_bank():
    # Bob's RV: 4 modules on one link -> one bank that IS the whole system
    ess = poll_ess({"main": (SimTransport(SimBank.of(4)), range(1, 5))})
    assert ess.bank_count == 1 and ess.module_count == 4
    assert not ess.has_alarm and 51 < ess.voltage_v < 53
