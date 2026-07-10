"""Modbus RTU frame construction — matches the Murata maintenance tool exactly.

Frame layouts and CRC verified against the decompiled tool (see docs/protocol/maintenance-tool.md):
raw Win32 serial, standard CRC-16/Modbus (init 0xFFFF, poly 0xA001), FC 0x03/0x04/0x06/0x10.

Read builders (FC 0x03/0x04) are safe. **Write builders (FC 0x06/0x10) produce DANGEROUS frames**
(CLAUDE.md §1) — this module only *builds bytes*; it never opens a port or transmits. Any code that
actually sends a write must be off-by-default behind `safety.allow_writes` and confirmed per session.
"""

from __future__ import annotations

# Modbus exception codes (from the module comm spec's error table)
ILLEGAL_FUNCTION = 0x01
ILLEGAL_DATA_ADDRESS = 0x02
ILLEGAL_DATA_VALUE = 0x03
SERVER_DEVICE_FAILURE = 0x04

_EXC_NAME = {1: "ILLEGAL_FUNCTION", 2: "ILLEGAL_DATA_ADDRESS", 3: "ILLEGAL_DATA_VALUE",
             4: "SERVER_DEVICE_FAILURE"}


class ModbusException(Exception):
    """A device returned a Modbus exception response (func | 0x80, code)."""

    def __init__(self, code: int):
        self.code = code
        super().__init__(f"Modbus exception {code:#04x} ({_EXC_NAME.get(code, '?')})")


def crc16(data: bytes) -> int:
    """Standard CRC-16/Modbus (init 0xFFFF, reflected poly 0xA001). Check: crc16(b'123456789')==0x4B37."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def _frame(payload: bytes) -> bytes:
    """Append CRC-16 low byte then high byte (Modbus RTU wire order)."""
    c = crc16(payload)
    return payload + bytes([c & 0xFF, (c >> 8) & 0xFF])


def _u16(v: int) -> bytes:
    return bytes([(v >> 8) & 0xFF, v & 0xFF])


# ── read frames (safe) ───────────────────────────────────────────────────────


def build_read_input(slave: int, address: int, count: int) -> bytes:
    """FC 0x04 Read Input Registers (how all module telemetry is read)."""
    return _frame(bytes([slave, 0x04]) + _u16(address) + _u16(count))


def build_read_holding(slave: int, address: int, count: int) -> bytes:
    """FC 0x03 Read Holding Registers. Safe probe of the *write* register space — if a device answers
    this, we can map its holding regs without writing anything. (Untested on bare modules.)"""
    return _frame(bytes([slave, 0x03]) + _u16(address) + _u16(count))


# ── write frames (DANGEROUS — build only) ────────────────────────────────────


def build_write_single(slave: int, address: int, value: int) -> bytes:
    """FC 0x06 Write Single Register. DANGEROUS. Matches the tool's write primitive (FUN_0040ab00)."""
    return _frame(bytes([slave, 0x06]) + _u16(address) + _u16(value))


def build_write_multiple(slave: int, address: int, values: list[int]) -> bytes:
    """FC 0x10 Write Multiple Registers. DANGEROUS. Matches the tool's FUN_0040a940."""
    n = len(values)
    payload = bytes([slave, 0x10]) + _u16(address) + _u16(n) + bytes([n * 2])
    for v in values:
        payload += _u16(v)
    return _frame(payload)


# ── decoded maintenance commands (from the tool reverse-engineering; see docs/protocol) ──
# These return frames only. Firing them is a §1 dangerous action requiring explicit confirmation,
# and whether a bare module honors them directly is an open question (still to be verified).

RESET_ALARM_LOCK = 0x0006   # value 1  — fault-clear
START_SCAN = 0x0007         # value 0x55
OPERATION_SETTING = 0x0065  # BITFIELD16


def reset_alarm_lock_frame(slave: int) -> bytes:
    """Fault-clear: write reg 0x0006 = 1. DANGEROUS; see §5 fault-clearing rules."""
    return build_write_single(slave, RESET_ALARM_LOCK, 1)
