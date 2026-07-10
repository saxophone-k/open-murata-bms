"""Interactive-setup wizard tests — feed scripted answers, confirm it writes a VALID config."""

import builtins

from omb import setup
from omb.config import load_config


def _answers(monkeypatch, seq):
    it = iter(seq)
    monkeypatch.setattr(builtins, "input", lambda *a: next(it))


def test_wizard_defaults_usb(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "_detect_serial", lambda: None)   # deterministic (no adapter)
    _answers(monkeypatch, ["", "", "", "", ""])                  # all defaults
    out = tmp_path / "config.yaml"
    setup.main([str(out)])
    c = load_config(str(out))
    assert c.ess.name == "My Batteries"
    assert c.banks[0].module_ids() == list(range(1, 5))          # default 4 modules
    assert c.banks[0].transport.serial.port == "/dev/ttyUSB0"
    assert c.integration.web.enabled is True                     # basic path on
    assert c.integration.mqtt.enabled is False


def test_wizard_gateway_and_mqtt(tmp_path, monkeypatch):
    _answers(monkeypatch, [
        "RV Pack", "6", "2",              # name, 6 modules, gateway
        "192.168.1.50", "502",           # gateway host + port
        "y", "192.168.1.10", "1883", "", # enable MQTT, broker host/port, no username
    ])
    out = tmp_path / "config.yaml"
    setup.main([str(out)])
    c = load_config(str(out))
    assert c.ess.name == "RV Pack"
    assert c.banks[0].module_ids() == list(range(1, 7))
    assert c.banks[0].transport.type.value == "rtu_over_tcp"
    assert c.banks[0].transport.host == "192.168.1.50"
    assert c.integration.mqtt.enabled is True
    assert c.integration.mqtt.host == "192.168.1.10"
