"""Config schema tests — run with no hardware (CI-safe)."""

from pathlib import Path

import pytest

from omb.config import Config, load_config

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "config" / "config.example.yaml"


def test_example_config_loads_and_validates():
    cfg = load_config(EXAMPLE)
    assert len(cfg.banks) == 1                 # example ships with one bank of 18
    assert cfg.total_modules() == 18
    assert cfg.safety.allow_writes is False    # writes must default OFF
    assert cfg.banks[0].module_ids() == list(range(1, 19))


def test_defaults_applied():
    cfg = Config.model_validate(
        {"banks": [{"id": "b1", "transport": {"type": "modbus_rtu",
                                              "serial": {"port": "/dev/ttyUSB0"}},
                    "slave_ids": [1]}]}
    )
    assert cfg.poll.interval_s == 5.0
    assert cfg.limits.max_modules_per_bank == 32
    assert cfg.integration.mqtt.discovery_prefix == "homeassistant"
    assert cfg.ess.nominal_voltage == 48


def test_rejects_too_many_modules_per_bank():
    with pytest.raises(ValueError):
        Config.model_validate(
            {"limits": {"max_modules_per_bank": 32},
             "banks": [{"id": "big",
                        "transport": {"type": "rtu_over_tcp", "host": "10.0.0.1"},
                        "slave_id_range": {"start": 1, "end": 40}}]}
        )


def test_rejects_duplicate_bank_ids():
    with pytest.raises(ValueError):
        Config.model_validate(
            {"banks": [
                {"id": "dup", "transport": {"type": "rtu_over_tcp", "host": "10.0.0.1"},
                 "slave_ids": [1]},
                {"id": "dup", "transport": {"type": "rtu_over_tcp", "host": "10.0.0.2"},
                 "slave_ids": [1]},
            ]}
        )


def test_rejects_both_slave_ids_and_range():
    with pytest.raises(ValueError):
        Config.model_validate(
            {"banks": [{"id": "b1",
                        "transport": {"type": "rtu_over_tcp", "host": "10.0.0.1"},
                        "slave_ids": [1, 2],
                        "slave_id_range": {"start": 1, "end": 2}}]}
        )


def test_tcp_transport_requires_host():
    with pytest.raises(ValueError):
        Config.model_validate(
            {"banks": [{"id": "b1", "transport": {"type": "modbus_tcp"},
                        "slave_ids": [1]}]}
        )
