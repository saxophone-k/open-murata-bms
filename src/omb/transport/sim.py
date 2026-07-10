"""Transport backed by the in-process simulator — no hardware, no network. For tests and demos."""

from __future__ import annotations

from omb.sim.module import SimBank


class SimTransport:
    """Adapts a `SimBank` to the `Transport` interface, so the whole driver stack runs against fakes."""

    def __init__(self, bank: SimBank):
        self.bank = bank

    def read_input_registers(self, unit: int, address: int, count: int) -> list[int] | None:
        return self.bank.read_input_registers(unit, address, count)

    def close(self) -> None:
        pass
