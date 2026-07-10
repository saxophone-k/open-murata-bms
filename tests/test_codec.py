"""Murata codec tests — including the exact quirks (byte-swapped ASCII, hi-word-first, DATE)."""

from datetime import date

from omb import codec


def test_ascii_byte_swap_roundtrip():
    # Spec example: "MURA" is transmitted as "UMAR".
    regs = codec.encode_ascii("MURA", 2)
    # low byte holds the earlier char: reg0 = 'M'(low) 'U'(high) = 0x554D
    assert regs == [0x554D, 0x4152]
    assert codec.decode_ascii(regs) == "MURA"


def test_ascii_real_sony_vendor():
    # Real registers observed on hardware for vendor "SONY": 0x4F53, 0x594E
    assert codec.decode_ascii([0x4F53, 0x594E]) == "SONY"


def test_ascii_odd_padding():
    regs = codec.encode_ascii("IJ1101M", 4)  # 7 chars -> 8 bytes, last 0x00
    assert codec.decode_ascii(regs) == "IJ1101M"


def test_uint32_high_word_first():
    assert codec.encode_uint(0x002DC785, 2) == [0x002D, 0xC785]
    assert codec.decode_uint([0x002D, 0xC785]) == 0x002DC785


def test_sint32_negative():
    regs = codec.encode_sint(-126, 2)
    assert codec.decode_sint(regs) == -126


def test_bitfield_roundtrip():
    assert codec.decode_bitfield([0x1000, 0x0000]) == 0x10000000  # Low Voltage alarm bit 28


def test_date_real_manufacture():
    # Real reg 0x1F96 -> 2015-12-22
    assert codec.decode_date([0x1F96]) == date(2015, 12, 22)
    assert codec.encode_date(date(2015, 12, 22)) == [0x1F96]
