"""Transport interface — the one seam every device driver talks through (ARCHITECTURE.md §Transport).

Implementations: `SimTransport` (the simulator, for tests/no-hardware), and `ModbusTransport`
(pymodbus over RS-485 serial or RTU-over-TCP gateways). Because it's a Protocol, anything with these
methods qualifies — no inheritance required.

Contract: a **silent device is normal** (per the Murata spec, an absent slave or an out-of-range read
just doesn't answer). So `read_input_registers` returns `None` on no-response/timeout rather than
raising — the driver treats `None` as "not there / try again," never as a crash.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Transport(Protocol):
    def read_input_registers(self, unit: int, address: int, count: int) -> list[int] | None:
        """`count` input registers (FC 0x04) from slave `unit`, or None on no-response/timeout."""
        ...

    def close(self) -> None:
        ...
