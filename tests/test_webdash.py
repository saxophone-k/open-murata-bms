"""Web dashboard tests — snapshot serializer + the stdlib HTTP server actually serving."""

import json
import urllib.request

from omb.integration.webdash import WebDashboard, snapshot
from omb.model.aggregate import poll_ess
from omb.sim.module import SimBank
from omb.transport.sim import SimTransport


def make_ess():
    # 5 configured, only 4 exist -> module 5 is 'missing' (offline placeholder)
    return poll_ess({"b": (SimTransport(SimBank.of(4, faulted_ids=(1,))), range(1, 6))},
                    names={"b": "Test Bank"}, ess_name="Test ESS")


def test_snapshot_shape_present_and_missing():
    snap = snapshot(make_ess())
    assert snap["name"] == "Test ESS" and snap["module_count"] == 4
    bank = snap["banks"][0]
    assert bank["name"] == "Test Bank" and bank["present"] == 4 and bank["expected"] == 5
    by_id = {m["id"]: m for m in bank["modules"]}
    assert by_id[5]["online"] is False                 # missing module -> offline placeholder
    assert by_id[1]["online"] is True and "low_voltage" in by_id[1]["faults"]
    assert "voltage_v" in by_id[2] and len(bank["modules"]) == 5


def test_server_serves_page_and_api():
    dash = WebDashboard(host="127.0.0.1", port=0)      # port 0 = ephemeral
    dash.start()
    try:
        port = dash._httpd.server_address[1]
        dash.update(make_ess())
        page = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3).read().decode()
        assert "<title>Battery Monitor</title>" in page
        api = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=3).read()
        data = json.loads(api)
        assert data["name"] == "Test ESS" and data["banks"][0]["present"] == 4
    finally:
        dash.close()
