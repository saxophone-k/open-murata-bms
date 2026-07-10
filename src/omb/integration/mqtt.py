"""MQTT publisher — ships ESS/bank/module readings to a broker with Home Assistant auto-discovery.

Thin wrapper over paho-mqtt (imported lazily). Points at whatever broker the config names — e.g. a
Mosquitto/HA broker on a TrueNAS box on the LAN. Publish-only; discovery configs and last states are
retained so HA shows values immediately (and re-discovers entities after a restart).
"""

from __future__ import annotations

import json

from omb.config import MqttConfig
from omb.integration import ha_discovery as ha


class MqttPublisher:
    def __init__(self, cfg: MqttConfig, client=None):
        self.cfg = cfg
        self.topics = ha.Topics(cfg.base_topic, cfg.discovery_prefix)
        self._client = client   # injectable for tests
        self._last_info = None  # most recent MQTTMessageInfo, for flush-on-close

    def connect(self) -> None:
        import paho.mqtt.client as mqtt
        try:
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)   # paho >= 2.0
        except (AttributeError, TypeError):
            c = mqtt.Client()                                    # older paho
        c.reconnect_delay_set(min_delay=1, max_delay=60)
        if self.cfg.username:
            c.username_pw_set(self.cfg.username, self.cfg.password)
        # last will: if the engine dies, HA sees every entity go 'unavailable'
        c.will_set(self.topics.status(), "offline", retain=True)
        c.connect(self.cfg.host, self.cfg.port, keepalive=60)
        c.loop_start()
        self._client = c
        self._pub(self.topics.status(), "online")

    def _pub(self, topic: str, payload, retain: bool = True) -> None:
        data = payload if isinstance(payload, str) else json.dumps(payload)
        try:
            self._last_info = self._client.publish(topic, data, retain=retain)
        except Exception:   # a broker hiccup must never crash the poll loop
            pass

    def flush(self, timeout: float = 5.0) -> None:
        """Block until queued publishes are on the wire — matters for --once, where we'd
        otherwise disconnect before paho's loop drains the outbound queue."""
        info = self._last_info
        if info is not None and hasattr(info, "wait_for_publish"):
            try:
                info.wait_for_publish(timeout)
            except Exception:
                pass

    def publish_discovery(self, ess) -> None:
        """One-time (or on-topology-change) HA discovery configs for every device."""
        if not self.cfg.ha_discovery:
            return
        t = self.topics
        for topic, cfg in ha.ess_discovery(t, ess):
            self._pub(topic, cfg)
        for bank in ess.banks.values():
            for topic, cfg in ha.bank_discovery(t, bank):
                self._pub(topic, cfg)
            for m in bank.modules.values():
                for topic, cfg in ha.module_discovery(t, bank.bank_id, bank.name, m):
                    self._pub(topic, cfg)

    def publish_states(self, ess) -> None:
        """Publish current state + attributes for the ESS, each bank, and each module — plus a
        per-entity availability signal so anything that stops answering goes 'unavailable' in HA
        (instead of showing stale retained values) while the engine keeps running."""
        t = self.topics
        self._pub(t.ess_state(), ha.rollup_state(ess))
        self._pub(t.ess_attr(), ha.ess_attrs(ess))
        self._pub(t.ess_status(), "online" if ess.module_count else "offline")
        for bank in ess.banks.values():
            bid = bank.bank_id
            self._pub(t.bank_state(bid), ha.rollup_state(bank))
            self._pub(t.bank_attr(bid), ha.bank_attrs(bank))
            self._pub(t.bank_status(bid), "online" if bank.present_count else "offline")
            for uid, m in bank.modules.items():
                self._pub(t.module_state(bid, uid), ha.module_state(m))
                self._pub(t.module_attr(bid, uid), ha.module_attrs(m))
            # availability for every configured module: online if it answered, else offline
            present = bank.modules
            for uid in (bank.expected_ids or list(present)):
                self._pub(t.module_status(bid, uid), "online" if uid in present else "offline")

    def close(self) -> None:
        if self._client is not None:
            try:
                self.flush()                 # drain the queue before we tear down
                self._client.disconnect()    # graceful DISCONNECT (loop still running to send it)
                self._client.loop_stop()     # then stop the network thread
            except Exception:
                pass
