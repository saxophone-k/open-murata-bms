"""Home Assistant MQTT Discovery — turn ESS/bank/module readings into HA entities automatically.

Pure payload builders (no MQTT client here, so they're fully unit-testable). The publisher
(`omb.integration.mqtt`) just ships what these return.

Model in HA: every module, every bank, and the whole ESS becomes a **device**; each metric is a
sensor on that device. To keep the broker chatty-but-simple, each device publishes ONE JSON **state
topic** and the sensors pull fields from it via `value_template` — plus a JSON **attributes topic**
for the bulky extras (per-cell arrays, alarm lists).

Topics (base = `mqtt.base_topic`, e.g. "open-murata-bms"):
    <base>/bank/<bank_id>/module/<uid>/state   + /attr
    <base>/bank/<bank_id>/state                + /attr
    <base>/ess/state                           + /attr
Discovery configs go under `<discovery_prefix>/<component>/<node>/<obj>/config` (retained).
"""

from __future__ import annotations

# metric: (key in state JSON, friendly name, unit, device_class, state_class)
_MODULE_SENSORS = [
    ("voltage_v", "Voltage", "V", "voltage", "measurement"),
    ("current_a", "Current", "A", "current", "measurement"),
    ("soc_pct", "State of Charge", "%", "battery", "measurement"),
    ("soh_pct", "State of Health", "%", None, "measurement"),
    ("max_cell_voltage_v", "Max Cell Voltage", "V", "voltage", "measurement"),
    ("min_cell_voltage_v", "Min Cell Voltage", "V", "voltage", "measurement"),
    ("cell_imbalance_mv", "Cell Imbalance", "mV", "voltage", "measurement"),
    ("max_cell_temp_c", "Max Cell Temp", "°C", "temperature", "measurement"),
    ("min_cell_temp_c", "Min Cell Temp", "°C", "temperature", "measurement"),
    ("remaining_capacity_ah", "Remaining Capacity", "Ah", None, "measurement"),
    ("cycle_count", "Cycle Count", None, None, "total_increasing"),
]
# roll-up tiers add power; drop per-module-only fields
_ROLLUP_SENSORS = [
    ("voltage_v", "Voltage", "V", "voltage", "measurement"),
    ("current_a", "Current", "A", "current", "measurement"),
    ("power_w", "Power", "W", "power", "measurement"),
    ("soc_pct", "State of Charge", "%", "battery", "measurement"),
    ("soh_pct", "State of Health", "%", None, "measurement"),
    ("remaining_capacity_ah", "Remaining Capacity", "Ah", None, "measurement"),
    ("full_charge_capacity_ah", "Full Capacity", "Ah", None, "measurement"),
    ("min_cell_voltage_v", "Min Cell Voltage", "V", "voltage", "measurement"),
    ("max_cell_voltage_v", "Max Cell Voltage", "V", "voltage", "measurement"),
    ("cell_imbalance_mv", "Cell Imbalance", "mV", "voltage", "measurement"),
    ("min_cell_temp_c", "Min Cell Temp", "°C", "temperature", "measurement"),
    ("max_cell_temp_c", "Max Cell Temp", "°C", "temperature", "measurement"),
]


class Topics:
    def __init__(self, base: str, discovery_prefix: str = "homeassistant"):
        self.base = base.rstrip("/")
        self.prefix = discovery_prefix.rstrip("/")

    def module_state(self, bank_id, uid): return f"{self.base}/bank/{bank_id}/module/{uid}/state"
    def module_attr(self, bank_id, uid): return f"{self.base}/bank/{bank_id}/module/{uid}/attr"
    def module_status(self, bank_id, uid): return f"{self.base}/bank/{bank_id}/module/{uid}/status"
    def bank_state(self, bank_id): return f"{self.base}/bank/{bank_id}/state"
    def bank_attr(self, bank_id): return f"{self.base}/bank/{bank_id}/attr"
    def bank_status(self, bank_id): return f"{self.base}/bank/{bank_id}/status"
    def ess_state(self): return f"{self.base}/ess/state"
    def ess_attr(self): return f"{self.base}/ess/attr"
    def ess_status(self): return f"{self.base}/ess/status"
    def status(self): return f"{self.base}/status"        # LWT availability for the whole engine

    def config(self, component, node, obj):
        return f"{self.prefix}/{component}/{node}/{obj}/config"


def _round(x):
    return round(x, 4) if isinstance(x, float) else x


def _sensor_configs(t: Topics, node: str, device: dict, state_topic: str, attr_topic: str,
                    specs: list, alarm_obj: str, entity_status: str) -> list[tuple[str, dict]]:
    """Build discovery configs for a set of value-template sensors + a problem binary_sensor.
    Availability requires BOTH the engine to be up (its LWT status) AND this entity's own status
    to be 'online' — so a module/bank that stops answering goes 'unavailable' in HA (greyed out)
    instead of showing stale retained values, even while the engine itself keeps running."""
    avail = [{"topic": t.status()}, {"topic": entity_status}]
    out = []
    for key, name, unit, dclass, sclass in specs:
        cfg = {
            "name": name,
            "state_topic": state_topic,
            "value_template": "{{ value_json." + key + " }}",
            "unique_id": f"omb_{node}_{key}",
            "device": device,
            "json_attributes_topic": attr_topic,
            "availability": avail,
            "availability_mode": "all",
        }
        if unit:
            cfg["unit_of_measurement"] = unit
        if dclass:
            cfg["device_class"] = dclass
        if sclass:
            cfg["state_class"] = sclass
        out.append((t.config("sensor", node, key), cfg))
    # alarm as a binary_sensor (problem)
    out.append((t.config("binary_sensor", node, "alarm"), {
        "name": "Alarm",
        "state_topic": state_topic,
        "value_template": "{{ 'ON' if value_json.has_alarm else 'OFF' }}",
        "payload_on": "ON", "payload_off": "OFF",
        "device_class": "problem",
        "unique_id": f"omb_{alarm_obj}_alarm",
        "device": device,
        "json_attributes_topic": attr_topic,
        "availability": avail,
        "availability_mode": "all",
    }))
    # human-readable fault names, so "Problem" isn't a mystery ("low_voltage" vs bare ON)
    out.append((t.config("sensor", node, "faults"), {
        "name": "Faults",
        "state_topic": state_topic,
        "value_template": "{{ value_json.alarm_text }}",
        "unique_id": f"omb_{node}_faults",
        "icon": "mdi:alert-circle-outline",
        "entity_category": "diagnostic",
        "device": device,
        "json_attributes_topic": attr_topic,
        "availability": avail,
        "availability_mode": "all",
    }))
    return out


# ── module ───────────────────────────────────────────────────────────────────

def module_state(r) -> dict:
    return {
        "voltage_v": _round(r.voltage_v), "current_a": _round(r.current_a),
        "soc_pct": r.soc_pct, "soh_pct": r.soh_pct, "cycle_count": r.cycle_count,
        "max_cell_voltage_v": _round(r.max_cell_voltage_v),
        "min_cell_voltage_v": _round(r.min_cell_voltage_v),
        "cell_imbalance_mv": r.cell_imbalance_mv,
        "max_cell_temp_c": r.max_cell_temp_c, "min_cell_temp_c": r.min_cell_temp_c,
        "remaining_capacity_ah": _round(r.remaining_capacity_ah),
        "has_alarm": r.has_alarm,
        "alarm_text": ", ".join(r.alarms) if r.alarms else "OK",
    }


def module_attrs(r) -> dict:
    return {
        "product_code": r.product_code, "vendor": r.vendor_name, "serial_number": r.serial_number,
        "software_version": r.software_version, "system_ready": r.system_ready,
        "charge_fet_on": r.charge_fet_on, "discharge_fet_on": r.discharge_fet_on,
        "alarms": r.alarms, "warnings": r.warnings,
        "cell_voltages_v": r.cell_voltages_v, "cell_temps_c": r.cell_temps_c,
        "config": r.config,
    }


def module_discovery(t: Topics, bank_id: str, bank_name: str, r) -> list[tuple[str, dict]]:
    node = f"bank_{bank_id}_module_{r.unit}"   # stable id (uses bank_id, not the display name)
    device = {"identifiers": [node], "name": f"{bank_name} Module {r.unit}",
              "manufacturer": r.vendor_name, "model": r.product_code,
              "via_device": f"bank_{bank_id}"}
    return _sensor_configs(t, node, device, t.module_state(bank_id, r.unit),
                           t.module_attr(bank_id, r.unit), _MODULE_SENSORS, node,
                           t.module_status(bank_id, r.unit))


# ── bank ─────────────────────────────────────────────────────────────────────

def rollup_state(r) -> dict:
    return {
        "voltage_v": _round(r.voltage_v), "current_a": _round(r.current_a), "power_w": r.power_w,
        "soc_pct": r.soc_pct, "soh_pct": r.soh_pct,
        "remaining_capacity_ah": _round(r.remaining_capacity_ah),
        "full_charge_capacity_ah": _round(r.full_charge_capacity_ah),
        "min_cell_voltage_v": _round(r.min_cell_voltage_v),
        "max_cell_voltage_v": _round(r.max_cell_voltage_v),
        "cell_imbalance_mv": r.cell_imbalance_mv,
        "min_cell_temp_c": r.min_cell_temp_c, "max_cell_temp_c": r.max_cell_temp_c,
        "has_alarm": r.has_alarm,
        "alarm_text": ", ".join(r.alarms) if r.alarms else "OK",
    }


def bank_discovery(t: Topics, r) -> list[tuple[str, dict]]:
    node = f"bank_{r.bank_id}"
    device = {"identifiers": [node], "name": r.name,
              "manufacturer": "open-murata-bms", "model": "Bank", "via_device": "ess"}
    return _sensor_configs(t, node, device, t.bank_state(r.bank_id), t.bank_attr(r.bank_id),
                           _ROLLUP_SENSORS, node, t.bank_status(r.bank_id))


def bank_attrs(r) -> dict:
    return {"present_modules": r.present_count, "missing_modules": r.missing_count,
            "alarms": r.alarms}


# ── ESS ──────────────────────────────────────────────────────────────────────

def ess_discovery(t: Topics, r) -> list[tuple[str, dict]]:
    node = "ess"
    device = {"identifiers": ["ess"], "name": r.name,
              "manufacturer": "open-murata-bms", "model": "ESS"}
    return _sensor_configs(t, node, device, t.ess_state(), t.ess_attr(), _ROLLUP_SENSORS, node,
                           t.ess_status())


def ess_attrs(r) -> dict:
    return {"bank_count": r.bank_count, "module_count": r.module_count, "alarms": r.alarms}
