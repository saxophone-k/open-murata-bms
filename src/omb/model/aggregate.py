"""Aggregation — roll module readings up the hierarchy: module -> bank -> ESS.

A **bank** = the modules on one RS-485 link (a rack, an RV shelf, a cabinet — however they're wired).
An **ESS** = all banks together. The config's `banks` list defines the topology, so the same code
covers 4 modules in an RV (one bank) or 4 banks x 18 modules in a room-sized system.

Aggregation assumes modules are **parallel** on a shared DC bus (the 48 V target): currents and
capacities **sum**, voltage is the shared bus level (mean), and cell extremes are the worst across the
whole group. (Series stacks would sum voltage instead — a future config flag.)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from omb.drivers.module_reader import ModuleReading, poll_modules


def _agg(children: list) -> dict:
    """Aggregate a list of parallel children (modules or banks) into one rolled-up view."""
    n = len(children)
    if n == 0:
        return dict(voltage_v=0.0, current_a=0.0, power_w=0.0, soc_pct=0.0, soh_pct=0.0,
                    remaining_capacity_ah=0.0, full_charge_capacity_ah=0.0,
                    min_cell_voltage_v=0.0, max_cell_voltage_v=0.0,
                    min_cell_temp_c=0.0, max_cell_temp_c=0.0)
    full = sum(c.full_charge_capacity_ah for c in children)
    remaining = sum(c.remaining_capacity_ah for c in children)
    current = sum(c.current_a for c in children)
    v = sum(c.voltage_v for c in children) / n
    return dict(
        voltage_v=round(v, 3),
        current_a=round(current, 3),
        power_w=round(v * current, 1),
        remaining_capacity_ah=round(remaining, 3),
        full_charge_capacity_ah=round(full, 3),
        soc_pct=round(remaining / full * 100, 1) if full else round(sum(c.soc_pct for c in children) / n, 1),
        soh_pct=round(sum(c.soh_pct for c in children) / n, 1),
        min_cell_voltage_v=min(c.min_cell_voltage_v for c in children),
        max_cell_voltage_v=max(c.max_cell_voltage_v for c in children),
        min_cell_temp_c=min(c.min_cell_temp_c for c in children),
        max_cell_temp_c=max(c.max_cell_temp_c for c in children),
    )


class _RollupMixin:
    """Shared rolled-up properties for the bank and ESS tiers."""
    _children: list

    @property
    def voltage_v(self) -> float: return _agg(self._children)["voltage_v"]
    @property
    def current_a(self) -> float: return _agg(self._children)["current_a"]
    @property
    def power_w(self) -> float: return _agg(self._children)["power_w"]
    @property
    def soc_pct(self) -> float: return _agg(self._children)["soc_pct"]
    @property
    def soh_pct(self) -> float: return _agg(self._children)["soh_pct"]
    @property
    def remaining_capacity_ah(self) -> float: return _agg(self._children)["remaining_capacity_ah"]
    @property
    def full_charge_capacity_ah(self) -> float: return _agg(self._children)["full_charge_capacity_ah"]
    @property
    def min_cell_voltage_v(self) -> float: return _agg(self._children)["min_cell_voltage_v"]
    @property
    def max_cell_voltage_v(self) -> float: return _agg(self._children)["max_cell_voltage_v"]
    @property
    def cell_imbalance_mv(self) -> float:
        a = _agg(self._children)
        return round((a["max_cell_voltage_v"] - a["min_cell_voltage_v"]) * 1000, 1)
    @property
    def min_cell_temp_c(self) -> float: return _agg(self._children)["min_cell_temp_c"]
    @property
    def max_cell_temp_c(self) -> float: return _agg(self._children)["max_cell_temp_c"]


@dataclass
class BankReading(_RollupMixin):
    """One bank = the modules on one RS-485 link."""
    bank_id: str
    modules: dict[int, ModuleReading]
    expected: int = 0
    name: str = ""                        # friendly display name; defaults to bank_id
    expected_ids: list[int] = field(default_factory=list)   # every configured id (for availability)

    def __post_init__(self):
        if not self.name:
            self.name = self.bank_id

    @property
    def _children(self) -> list: return list(self.modules.values())
    @property
    def present_count(self) -> int: return len(self.modules)
    @property
    def missing_count(self) -> int: return max(0, self.expected - self.present_count)
    @property
    def missing_ids(self) -> list[int]:
        return [uid for uid in self.expected_ids if uid not in self.modules]
    @property
    def alarms(self) -> list[str]:
        return [f"module{uid}: {a}" for uid, m in self.modules.items() for a in m.alarms]
    @property
    def has_alarm(self) -> bool: return any(m.has_alarm for m in self.modules.values())


@dataclass
class EssReading(_RollupMixin):
    """The whole energy storage system = all banks."""
    banks: dict[str, BankReading]
    name: str = "Energy Storage System"

    @property
    def _children(self) -> list: return list(self.banks.values())
    @property
    def bank_count(self) -> int: return len(self.banks)
    @property
    def module_count(self) -> int: return sum(b.present_count for b in self.banks.values())
    @property
    def alarms(self) -> list[str]:
        return [f"{bid}/{a}" for bid, b in self.banks.items() for a in b.alarms]
    @property
    def has_alarm(self) -> bool: return any(b.has_alarm for b in self.banks.values())


def poll_bank(transport, bank_id: str, unit_ids, name: str | None = None) -> BankReading:
    ids = list(unit_ids)
    return BankReading(bank_id, poll_modules(transport, ids), expected=len(ids),
                       name=name or bank_id, expected_ids=ids)


def poll_ess(banks: dict[str, tuple], names: dict[str, str] | None = None,
             ess_name: str = "Energy Storage System") -> EssReading:
    """`banks`: {bank_id: (transport, unit_ids)}. `names`: optional {bank_id: display name}."""
    names = names or {}
    out = {bid: poll_bank(tp, bid, ids, name=names.get(bid)) for bid, (tp, ids) in banks.items()}
    return EssReading(out, name=ess_name)
