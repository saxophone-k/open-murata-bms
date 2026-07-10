"""Configuration schema + loader for open-murata-bms.

Config-driven topology (see ARCHITECTURE.md): an **ESS** (energy storage system) made of one or more
**banks**, each bank a set of modules on one RS-485 link (a rack, an RV shelf, a cabinet — however
they're physically wired). Nothing install-specific is hardcoded in the repo.

This module has no hardware/network dependencies (only pydantic + pyyaml), so it is fully
unit-testable and safe to import anywhere.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

# ── Transport ────────────────────────────────────────────────────────────────


class TransportType(str, Enum):
    modbus_tcp = "modbus_tcp"        # native Modbus/TCP
    rtu_over_tcp = "rtu_over_tcp"    # RS-485 RTU frames tunneled over TCP (EW11/Waveshare gateway)
    modbus_rtu = "modbus_rtu"        # direct serial (USB-RS485; bench / single module)


class Parity(str, Enum):
    none = "N"
    even = "E"   # Murata modules require Even
    odd = "O"


class SerialParams(BaseModel):
    """Serial line params. Murata IJ1101M default: 230400 / 8 / Even / 1."""
    port: str
    baudrate: int = 230400
    bytesize: int = 8
    parity: Parity = Parity.even
    stopbits: int = 1


class TransportConfig(BaseModel):
    type: TransportType
    host: str | None = None            # for modbus_tcp / rtu_over_tcp
    port: int = 502                       # gateway TCP port (Murata modules use 502)
    serial: SerialParams | None = None  # for modbus_rtu

    @model_validator(mode="after")
    def _check(self) -> TransportConfig:
        if self.type in (TransportType.modbus_tcp, TransportType.rtu_over_tcp):
            if not self.host:
                raise ValueError(f"transport '{self.type.value}' requires 'host'")
        elif self.type == TransportType.modbus_rtu:
            if self.serial is None:
                raise ValueError("transport 'modbus_rtu' requires 'serial'")
        return self


# ── Bank (a set of modules on one RS-485 link) ───────────────────────────────


class SlaveIdRange(BaseModel):
    start: int = Field(ge=1, le=247)
    end: int = Field(ge=1, le=247)

    @model_validator(mode="after")
    def _check(self) -> SlaveIdRange:
        if self.end < self.start:
            raise ValueError("slave_id_range: 'end' must be >= 'start'")
        return self

    def ids(self) -> list[int]:
        return list(range(self.start, self.end + 1))


class BankConfig(BaseModel):
    """One bank = the modules on one RS-485 link (behind one gateway or adapter)."""
    id: str                               # stable technical id (e.g. "BAT2-EBAT-18")
    name: str | None = None            # friendly HA display name (defaults to id)
    transport: TransportConfig
    timeout_ms: int = 25                  # Murata recommends 25 ms
    retries: int = 2
    slave_ids: list[int] | None = None
    slave_id_range: SlaveIdRange | None = None

    @model_validator(mode="after")
    def _resolve(self) -> BankConfig:
        if (self.slave_ids is None) == (self.slave_id_range is None):
            raise ValueError(
                f"bank '{self.id}': set exactly one of 'slave_ids' or 'slave_id_range'"
            )
        ids = self.module_ids()
        if not ids:
            raise ValueError(f"bank '{self.id}': no modules defined")
        if len(set(ids)) != len(ids):
            raise ValueError(f"bank '{self.id}': duplicate slave ids")
        for i in ids:
            if not (1 <= i <= 247):
                raise ValueError(f"bank '{self.id}': slave id {i} out of Modbus range 1..247")
        return self

    def module_ids(self) -> list[int]:
        if self.slave_ids is not None:
            return list(self.slave_ids)
        assert self.slave_id_range is not None
        return self.slave_id_range.ids()


# ── Integration / safety / misc ──────────────────────────────────────────────


class Limits(BaseModel):
    # RS-485 tolerates ~32 unit loads per un-repeated segment.
    max_modules_per_bank: int = 32


class Poll(BaseModel):
    interval_s: float = Field(default=5.0, gt=0)


class MqttConfig(BaseModel):
    enabled: bool = False         # advanced path: publish to an MQTT broker / Home Assistant (opt-in)
    host: str = "127.0.0.1"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    base_topic: str = "open-murata-bms"
    discovery_prefix: str = "homeassistant"
    ha_discovery: bool = True


class WebConfig(BaseModel):
    """Built-in web dashboard — the 'basic setup'. No broker or Home Assistant needed: the engine
    serves a live page itself, so a non-technical user just opens http://<machine-ip>:<port>."""
    enabled: bool = True          # on by default: instant zero-config view; no broker/HA required
    host: str = "0.0.0.0"         # listen on all interfaces so other devices on the LAN can reach it
    port: int = 8080


class Integration(BaseModel):
    mqtt: MqttConfig = Field(default_factory=MqttConfig)
    web: WebConfig = Field(default_factory=WebConfig)


class Thresholds(BaseModel):
    """Protection thresholds for the software supervisor (Phase 6). None = unset."""
    cell_uv_mv: int | None = None
    cell_ov_mv: int | None = None
    soc_floor_pct: float | None = None


class Safety(BaseModel):
    # Master guards for dangerous writes — see CLAUDE.md §1. Off by default.
    allow_writes: bool = False
    allow_fault_clear: bool = False
    thresholds: Thresholds = Field(default_factory=Thresholds)


class EssConfig(BaseModel):
    """The whole energy storage system."""
    name: str = "My Battery System"
    nominal_voltage: int = 48


class Config(BaseModel):
    ess: EssConfig = Field(default_factory=EssConfig)
    banks: list[BankConfig]
    limits: Limits = Field(default_factory=Limits)
    poll: Poll = Field(default_factory=Poll)
    integration: Integration = Field(default_factory=Integration)
    safety: Safety = Field(default_factory=Safety)
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _check(self) -> Config:
        if not self.banks:
            raise ValueError("config needs at least one bank")
        ids = [b.id for b in self.banks]
        if len(set(ids)) != len(ids):
            raise ValueError("bank ids must be unique")
        for b in self.banks:
            n = len(b.module_ids())
            if n > self.limits.max_modules_per_bank:
                raise ValueError(
                    f"bank '{b.id}' has {n} modules > limits.max_modules_per_bank "
                    f"({self.limits.max_modules_per_bank})"
                )
        return self

    def total_modules(self) -> int:
        return sum(len(b.module_ids()) for b in self.banks)


def load_config(path: str | Path) -> Config:
    """Load and validate a YAML config file."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"config file {path} did not parse to a mapping")
    return Config.model_validate(data)
