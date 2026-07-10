"""MQTT / Home Assistant discovery tests — pure payload builders + publisher (fake client, no broker)."""

import json

from omb.config import MqttConfig
from omb.integration import ha_discovery as ha
from omb.integration.mqtt import MqttPublisher
from omb.model.aggregate import poll_ess
from omb.sim.module import SimBank
from omb.transport.sim import SimTransport


def make_ess():
    banks = {
        "bank1": (SimTransport(SimBank.of(4, faulted_ids=(1,))), range(1, 5)),
        "bank2": (SimTransport(SimBank.of(4)), range(1, 5)),
    }
    return poll_ess(banks)


def test_module_state_and_attrs():
    m = make_ess().banks["bank1"].modules[2]     # healthy module
    s = ha.module_state(m)
    assert s["soc_pct"] == 82.0 and s["has_alarm"] is False and "voltage_v" in s
    attrs = ha.module_attrs(m)
    assert len(attrs["cell_voltages_v"]) == 16 and attrs["vendor"] == "SONY"


def test_module_discovery_shape_with_real_naming():
    t = ha.Topics("open-murata-bms", "homeassistant")
    m = make_ess().banks["bank1"].modules[2]
    # real install: stable id from the integrator plate, friendly French display name
    cfgs = ha.module_discovery(t, "BAT2-EBAT-18", "Étagère 18", m)
    topics = [c[0] for c in cfgs]
    assert all(top.endswith("/config") for top in topics)
    assert any("binary_sensor" in top for top in topics)          # the alarm entity
    # identifiers/state topics use the STABLE id; the display name uses the friendly name
    assert all(cfg["device"]["identifiers"] == ["bank_BAT2-EBAT-18_module_2"] for _, cfg in cfgs)
    assert all(cfg["device"]["name"] == "Étagère 18 Module 2" for _, cfg in cfgs)
    assert all(cfg["state_topic"] == "open-murata-bms/bank/BAT2-EBAT-18/module/2/state" for _, cfg in cfgs)
    # availability requires BOTH the engine status AND the module's own status ('all' mode)
    for _, cfg in cfgs:
        topics = {a["topic"] for a in cfg["availability"]}
        assert cfg["availability_mode"] == "all"
        assert "open-murata-bms/status" in topics
        assert "open-murata-bms/bank/BAT2-EBAT-18/module/2/status" in topics


class FakeClient:
    def __init__(self):
        self.pubs = []

    def publish(self, topic, payload, retain=False):
        self.pubs.append((topic, payload, retain))


def test_publisher_publishes_discovery_and_states():
    ess = make_ess()
    pub = MqttPublisher(MqttConfig(base_topic="omb"), client=FakeClient())
    pub.publish_discovery(ess)
    pub.publish_states(ess)
    topics = [p[0] for p in pub._client.pubs]

    assert any(t.startswith("homeassistant/") and t.endswith("/config") for t in topics)
    assert "omb/ess/state" in topics
    assert "omb/bank/bank1/state" in topics
    assert "omb/bank/bank1/module/2/state" in topics
    # every payload is valid JSON, except the plain-string availability topics
    for topic, payload, _ in pub._client.pubs:
        if topic.endswith("/status"):
            assert payload in ("online", "offline")
        else:
            json.loads(payload)
    # discovery configs are retained
    disc = [p for p in pub._client.pubs if p[0].endswith("/config")]
    assert disc and all(retain for _, _, retain in disc)


def test_per_module_availability_online_offline():
    tp = SimTransport(SimBank.of(4))
    ess = poll_ess({"b": (tp, range(1, 6))})   # 5 configured, only 4 exist -> #5 is missing
    pub = MqttPublisher(MqttConfig(base_topic="omb"), client=FakeClient())
    pub.publish_states(ess)
    pubs = {t: p for t, p, _ in pub._client.pubs}
    assert pubs["omb/bank/b/module/4/status"] == "online"
    assert pubs["omb/bank/b/module/5/status"] == "offline"   # missing -> HA marks it unavailable
    assert pubs["omb/bank/b/status"] == "online"             # bank still has members
    assert pubs["omb/ess/status"] == "online"


def test_discovery_can_be_disabled():
    pub = MqttPublisher(MqttConfig(ha_discovery=False), client=FakeClient())
    pub.publish_discovery(make_ess())
    assert pub._client.pubs == []
