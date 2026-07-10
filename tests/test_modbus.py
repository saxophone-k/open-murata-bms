"""Modbus frame tests — our frames must be byte-identical to the decompiled maintenance tool."""

from omb import modbus


def test_crc16_standard_check_value():
    # The canonical CRC-16/Modbus check value.
    assert modbus.crc16(b"123456789") == 0x4B37


def test_read_input_frame_layout():
    # slave 1, FC04, addr 0x0000, count 75 (0x4B) — the module poll.
    f = modbus.build_read_input(1, 0x0000, 75)
    assert f[:6] == bytes([0x01, 0x04, 0x00, 0x00, 0x00, 0x4B])
    assert modbus.crc16(f[:6]) == f[6] | (f[7] << 8)   # appended CRC is lo,hi


def test_fault_clear_frame_matches_tool():
    # The decompiled fault-clear: Write Single Register, addr 0x0006, value 1.
    f = modbus.reset_alarm_lock_frame(0x0A)  # to slave 10 (example)
    assert f[:6] == bytes([0x0A, 0x06, 0x00, 0x06, 0x00, 0x01])
    # full frame ends with a valid CRC
    assert modbus.crc16(f[:-2]) == f[-2] | (f[-1] << 8)


def test_write_multiple_length_matches_tool_formula():
    # FC 0x10 frame length is 9 + 2*N (the tool's `count*2 + 9`).
    for n in (1, 2, 6):
        f = modbus.build_write_multiple(1, 0x0063, [0] * n)
        assert len(f) == 9 + 2 * n
        assert f[1] == 0x10 and f[6] == n * 2  # func code + byte count


def test_read_holding_is_fc03():
    f = modbus.build_read_holding(1, 0x0006, 4)
    assert f[1] == 0x03
