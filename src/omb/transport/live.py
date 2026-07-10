"""Live Modbus transport over real hardware — RS-485 serial or RTU-over-TCP (EW11/Waveshare gateways).

pymodbus is imported lazily so the rest of the package (and the tests) never depend on it. Built from a
validated `TransportConfig` (see `omb.config`), so a stranger's whole install comes from one config file.
This transport is **read-only** (FC 0x04); dangerous writes live on a separate, guarded path (CLAUDE.md §1).
"""

from __future__ import annotations

from omb.config import TransportConfig, TransportType


class ModbusTransport:
    def __init__(self, cfg: TransportConfig, timeout_s: float = 0.5, retries: int = 2):
        self.cfg = cfg
        self._timeout = timeout_s
        self._retries = retries
        self._reconnect_after = 0.0   # monotonic time gate: throttle reconnect attempts
        self._client = self._build_client()
        # pymodbus renamed the unit-id kwarg 'slave' -> 'device_id' in 3.x; detect once.
        import inspect
        params = inspect.signature(self._client.read_input_registers).parameters
        self._unit_kw = "device_id" if "device_id" in params else "slave"

    def _build_client(self):
        cfg = self.cfg
        if cfg.type in (TransportType.modbus_tcp, TransportType.rtu_over_tcp):
            from pymodbus.client import ModbusTcpClient
            framer = None
            if cfg.type == TransportType.rtu_over_tcp:
                try:
                    from pymodbus.framer import FramerType
                    framer = FramerType.RTU
                except Exception:
                    framer = None
            kwargs = dict(host=cfg.host, port=cfg.port, timeout=self._timeout, retries=self._retries)
            if framer is not None:
                kwargs["framer"] = framer
            return ModbusTcpClient(**kwargs)
        # modbus_rtu (direct serial)
        from pymodbus.client import ModbusSerialClient
        s = cfg.serial
        return ModbusSerialClient(port=s.port, baudrate=s.baudrate, bytesize=s.bytesize,
                                  parity=s.parity.value, stopbits=s.stopbits,
                                  timeout=self._timeout, retries=self._retries)

    def connect(self) -> bool:
        ok = self._client.connect()
        self._tune_serial_latency()
        return ok

    def _tune_serial_latency(self) -> None:
        """FTDI/PL2303 USB-serial adapters default to a 16 ms latency timer, which cripples
        request/response Modbus polling (every transaction waits up to 16 ms for the USB buffer).
        Dropping it to 1 ms makes a full 18-module sweep ~12x faster (3.7 s -> 0.3 s). Best-effort:
        needs root or a udev rule; silently skipped otherwise (see packaging/99-ftdi-latency.rules)."""
        if self.cfg.type != TransportType.modbus_rtu or not self.cfg.serial:
            return
        import os
        # resolve /dev/serial/by-id/... symlink to the real ttyUSBn before finding its sysfs node
        dev = os.path.basename(os.path.realpath(str(self.cfg.serial.port)))
        path = f"/sys/bus/usb-serial/devices/{dev}/latency_timer"
        try:
            with open(path) as f:
                if f.read().strip() == "1":
                    return
            with open(path, "w") as f:
                f.write("1")
        except OSError:
            pass   # not an FTDI, not Linux, or no permission — a udev rule can set it instead

    def read_input_registers(self, unit: int, address: int, count: int) -> list[int] | None:
        # A non-responding / flaky module must NOT crash the poll — pymodbus raises
        # ModbusIOException when it exhausts retries; treat that (and any error result) as
        # "this unit didn't answer this cycle". The caller skips it and retries next poll.
        try:
            r = self._client.read_input_registers(address, count=count, **{self._unit_kw: unit})
        except Exception:
            # could be a dead module OR the whole link dropped (USB adapter unplugged,
            # gateway rebooted). Attempt a throttled reconnect so we recover automatically
            # when it comes back, without a reconnect storm during a full outage.
            self._maybe_reconnect()
            return None
        if r.isError():
            return None
        return list(r.registers)

    def _maybe_reconnect(self) -> None:
        import time
        now = time.monotonic()
        if now < self._reconnect_after:
            return
        self._reconnect_after = now + 2.0     # at most one reconnect attempt every 2 s
        try:
            self._client.close()
        except Exception:
            pass
        try:
            if self._client.connect():
                self._tune_serial_latency()   # a replugged adapter resets to 16 ms
        except Exception:
            pass

    def close(self) -> None:
        self._client.close()
