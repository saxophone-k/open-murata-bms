"""Murata Modbus data-type encode/decode.

From the IJ1101M Communication Specification:
- Big-endian words. UINT32/SINT32 span 2 registers, **high word first** (lower address = high half).
- BITFIELD16/32/64 behave like unsigned ints of that width, high word first.
- **ASCII is byte-swapped**: two chars per register, swapped within the register. The lower-addressed
  char goes in the *low* byte. So "MURA" is transmitted "UMAR". Odd final byte is 0x00.
- DATE packs into one 16-bit register: bit15..9 = year-2000, bit8..5 = month, bit4..0 = day.

A "word" here is one 16-bit Modbus register value (0..65535). These helpers convert between Python
values and lists of words, so both the simulator (encode) and the driver (decode) share one source
of truth.
"""

from __future__ import annotations

from datetime import date


def _u16(v: int) -> int:
    return v & 0xFFFF


# ── unsigned / signed integers (high word first) ─────────────────────────────


def encode_uint(value: int, words: int) -> list[int]:
    if value < 0:
        raise ValueError("encode_uint got a negative value")
    return [(value >> (16 * (words - 1 - i))) & 0xFFFF for i in range(words)]


def decode_uint(regs: list[int]) -> int:
    v = 0
    for r in regs:
        v = (v << 16) | _u16(r)
    return v


def encode_sint(value: int, words: int) -> list[int]:
    bits = 16 * words
    if value < 0:
        value += 1 << bits
    return encode_uint(value, words)


def decode_sint(regs: list[int]) -> int:
    v = decode_uint(regs)
    bits = 16 * len(regs)
    if v >= (1 << (bits - 1)):
        v -= 1 << bits
    return v


# BITFIELDs are just unsigned ints of the given width (high word first).
encode_bitfield = encode_uint
decode_bitfield = decode_uint


# ── byte-swapped ASCII ───────────────────────────────────────────────────────


def encode_ascii(text: str, words: int) -> list[int]:
    """Encode `text` into `words` registers, Murata byte-swapped, 0x00-padded."""
    raw = text.encode("ascii")
    needed = words * 2
    if len(raw) > needed:
        raise ValueError(f"'{text}' needs > {needed} bytes")
    raw = raw + b"\x00" * (needed - len(raw))
    regs = []
    for i in range(words):
        lo = raw[2 * i]        # lower-addressed char -> LOW byte (the swap)
        hi = raw[2 * i + 1]
        regs.append((hi << 8) | lo)
    return regs


def decode_ascii(regs: list[int]) -> str:
    chars = []
    for r in regs:
        chars.append(r & 0xFF)          # low byte first
        chars.append((r >> 8) & 0xFF)   # then high byte
    return bytes(chars).rstrip(b"\x00").decode("ascii", errors="replace")


# ── DATE ─────────────────────────────────────────────────────────────────────


def encode_date(d: date) -> list[int]:
    yy = d.year - 2000
    if not (0 <= yy <= 0x7F):
        raise ValueError("DATE year out of range 2000..2127")
    return [((yy & 0x7F) << 9) | ((d.month & 0x0F) << 5) | (d.day & 0x1F)]


def decode_date(regs: list[int]) -> date:
    r = _u16(regs[0])
    yy = (r >> 9) & 0x7F
    mm = (r >> 5) & 0x0F
    dd = r & 0x1F
    return date(2000 + yy, mm or 1, dd or 1)
