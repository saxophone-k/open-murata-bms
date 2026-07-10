"""Expose a SimBank over Modbus-TCP so any client (our stack, or a Modbus tool) can poll fake
modules with no hardware.

Real Murata modules are RTU/serial; we serve TCP purely for convenience (RTU-over-TCP clients and
Modbus-TCP clients both work). pymodbus is imported lazily so the rest of the package — and the
tests — do not depend on it.

CLI:
    python -m omb.sim.server --port 5020 --modules 18 --faulted 1
Then point a client at 127.0.0.1:5020, unit ids 1..18, FC 0x04 @ 0x0000 count 75.
"""

from __future__ import annotations

import argparse

from omb.sim.module import SimBank


def build_server_context(bank: SimBank):
    """Build a pymodbus ServerContext snapshotting each module's input registers."""
    from pymodbus.datastore import (
        ModbusServerContext,
        ModbusSlaveContext,
        ModbusSparseDataBlock,
    )

    slaves = {}
    for uid, mod in bank.modules.items():
        regs = mod.state.to_input_registers()
        block = ModbusSparseDataBlock({addr: val for addr, val in enumerate(regs)})
        slaves[uid] = ModbusSlaveContext(ir=block, zero_mode=True)
    return ModbusServerContext(slaves=slaves, single=False)


def run(bank: SimBank, host: str = "0.0.0.0", port: int = 5020) -> None:
    from pymodbus.server import StartTcpServer

    context = build_server_context(bank)
    print(f"omb simulator: {len(bank.modules)} modules on {host}:{port} "
          f"(unit ids {min(bank.modules)}..{max(bank.modules)}, FC04 @0x0000 count 75)")
    StartTcpServer(context=context, address=(host, port))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Murata module simulator (Modbus-TCP)")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5020)
    p.add_argument("--modules", type=int, default=18, help="number of modules (slave ids 1..N)")
    p.add_argument("--faulted", type=int, nargs="*", default=[],
                   help="slave ids to start in the under-voltage/permanent-failure state")
    args = p.parse_args(argv)
    bank = SimBank.of(count=args.modules, faulted_ids=tuple(args.faulted))
    run(bank, args.host, args.port)


if __name__ == "__main__":
    main()
