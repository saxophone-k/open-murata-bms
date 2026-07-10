"""Built-in web dashboard — the zero-dependency 'basic setup'.

For users who don't run (or don't want) MQTT + Home Assistant, the engine serves its own live page.
Point a browser at http://<machine-ip>:<port> and see the whole ESS -> banks -> modules, updating
live. Pure Python stdlib (http.server + threading), read-only, no external assets — the HTML/CSS/JS
is inlined so it works on an offline LAN with nothing else installed.

Wiring: the poll loop calls `update(ess)` each cycle to refresh an in-memory snapshot; the HTTP
handler just serves the latest snapshot as JSON, and the page polls `/api/state` to redraw.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("omb")


def snapshot(ess) -> dict:
    """Serialize an EssReading into the nested JSON the dashboard renders (present + missing modules)."""
    banks = []
    for b in ess.banks.values():
        modules = []
        for uid, m in b.modules.items():
            modules.append({
                "id": uid, "online": True,
                "voltage_v": round(m.voltage_v, 2), "current_a": round(m.current_a, 1),
                "soc_pct": m.soc_pct, "soh_pct": m.soh_pct, "cycle_count": m.cycle_count,
                "min_cell_v": round(m.min_cell_voltage_v, 3), "max_cell_v": round(m.max_cell_voltage_v, 3),
                "imbalance_mv": m.cell_imbalance_mv,
                "min_temp_c": round(m.min_cell_temp_c, 1), "max_temp_c": round(m.max_cell_temp_c, 1),
                "faults": list(m.alarms), "warnings": list(m.warnings),
            })
        for uid in b.missing_ids:                       # placeholders so the UI can grey them out
            modules.append({"id": uid, "online": False})
        modules.sort(key=lambda x: x["id"])
        banks.append({
            "id": b.bank_id, "name": b.name,
            "voltage_v": round(b.voltage_v, 1), "current_a": round(b.current_a, 1),
            "power_w": b.power_w, "soc_pct": b.soc_pct, "soh_pct": b.soh_pct,
            "present": b.present_count, "expected": b.expected, "missing_ids": list(b.missing_ids),
            "has_alarm": b.has_alarm, "alarms": list(b.alarms), "modules": modules,
        })
    return {
        "name": ess.name, "generated": datetime.now().isoformat(timespec="seconds"),
        "voltage_v": round(ess.voltage_v, 1), "current_a": round(ess.current_a, 1),
        "power_w": ess.power_w, "soc_pct": ess.soc_pct, "soh_pct": ess.soh_pct,
        "module_count": ess.module_count, "bank_count": ess.bank_count,
        "has_alarm": ess.has_alarm, "alarms": list(ess.alarms), "banks": banks,
    }


class _Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(_PAGE.encode(), "text/html; charset=utf-8")
        elif path == "/api/state":
            with self.server.lock:                       # type: ignore[attr-defined]
                body = self.server.latest                # type: ignore[attr-defined]
            self._send(body, "application/json")
        else:
            self.send_error(404)

    def log_message(self, *args) -> None:                # keep the engine log clean
        pass


class WebDashboard:
    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self.host = host
        self.port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._httpd = ThreadingHTTPServer((self.host, self.port), _Handler)
        self._httpd.lock = threading.Lock()              # type: ignore[attr-defined]
        self._httpd.latest = b'{"name":"starting up...","banks":[]}'  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        log.info("web dashboard on http://%s:%d", self.host, self.port)

    def update(self, ess) -> None:
        if self._httpd is None:
            return
        body = json.dumps(snapshot(ess)).encode()
        with self._httpd.lock:                           # type: ignore[attr-defined]
            self._httpd.latest = body                    # type: ignore[attr-defined]

    def close(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass


# ── the page (self-contained: inline CSS + JS, no external requests) ─────────────────────────────
_PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Battery Monitor</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         background:#0f1419; color:#e6e9ee; }
  header { padding:16px 20px; background:#161c26; border-bottom:1px solid #263041;
           position:sticky; top:0; display:flex; flex-wrap:wrap; align-items:baseline; gap:8px 20px; }
  header h1 { margin:0; font-size:20px; font-weight:600; }
  header .sub { color:#8b95a5; font-size:13px; }
  .kpis { display:flex; flex-wrap:wrap; gap:22px; margin-left:auto; }
  .kpi b { font-size:20px; } .kpi span { color:#8b95a5; font-size:12px; display:block; }
  .banner { background:#5a1e1e; color:#ffd9d9; padding:8px 20px; font-size:14px; }
  .wrap { padding:16px 20px 40px; }
  .bank { margin-bottom:26px; }
  .bank h2 { font-size:16px; margin:0 0 4px; }
  .bank .meta { color:#8b95a5; font-size:13px; margin-bottom:10px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(190px,1fr)); gap:12px; }
  .mod { background:#161c26; border:1px solid #263041; border-radius:10px; padding:12px; }
  .mod.alarm { border-color:#b3452f; }
  .mod.offline { opacity:.4; }
  .mod .top { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px; }
  .mod .id { font-weight:600; } .mod .soc { font-size:20px; font-weight:600; }
  .bar { height:6px; background:#263041; border-radius:4px; overflow:hidden; margin:6px 0 10px; }
  .bar > i { display:block; height:100%; background:#3d9970; }
  .row { display:flex; justify-content:space-between; font-size:13px; padding:2px 0; color:#c3cad6; }
  .row .k { color:#8b95a5; }
  .fault { margin-top:8px; background:#3a1512; color:#ff9c8a; border-radius:6px; padding:5px 8px; font-size:12px; }
  .offbadge { margin-top:8px; color:#8b95a5; font-size:12px; }
  footer { color:#5c6675; font-size:12px; padding:0 20px 24px; }
</style></head>
<body>
<header>
  <div><h1 id="ess">Battery Monitor</h1><div class="sub" id="sub">connecting…</div></div>
  <div class="kpis" id="kpis"></div>
</header>
<div id="banner"></div>
<div class="wrap" id="wrap"></div>
<footer id="foot"></footer>
<script>
const $ = s => document.querySelector(s);
function kpi(v,l){ return `<div class="kpi"><b>${v}</b><span>${l}</span></div>`; }
function fmt(n,d=1){ return (n===undefined||n===null)?'–':Number(n).toFixed(d); }
async function tick(){
  try {
    const r = await fetch('/api/state',{cache:'no-store'});
    const d = await r.json();
    $('#ess').textContent = d.name || 'Battery Monitor';
    $('#sub').textContent = `${d.module_count||0} modules · ${d.bank_count||0} bank(s) · updated ${(''+d.generated).replace('T',' ')}`;
    $('#kpis').innerHTML = kpi(fmt(d.voltage_v)+' V','Voltage')+kpi((d.current_a>=0?'+':'')+fmt(d.current_a)+' A','Current')
      + kpi(fmt(d.power_w,0)+' W','Power')+kpi(fmt(d.soc_pct,0)+' %','State of Charge')+kpi(fmt(d.soh_pct,0)+' %','Health');
    $('#banner').innerHTML = d.has_alarm ? `<div class="banner">⚠ ${(d.alarms||[]).join(' · ')}</div>` : '';
    let html='';
    for(const b of (d.banks||[])){
      html += `<div class="bank"><h2>${b.name}</h2><div class="meta">${b.present}/${b.expected} modules · ${fmt(b.voltage_v)} V · ${(b.current_a>=0?'+':'')}${fmt(b.current_a)} A · SOC ${fmt(b.soc_pct,0)}%</div><div class="grid">`;
      for(const m of (b.modules||[])){
        if(!m.online){ html += `<div class="mod offline"><div class="top"><span class="id">Module ${m.id}</span></div><div class="offbadge">offline</div></div>`; continue; }
        const al = (m.faults&&m.faults.length);
        html += `<div class="mod ${al?'alarm':''}">
          <div class="top"><span class="id">Module ${m.id}</span><span class="soc">${fmt(m.soc_pct,0)}%</span></div>
          <div class="bar"><i style="width:${Math.max(0,Math.min(100,m.soc_pct))}%"></i></div>
          <div class="row"><span class="k">Voltage</span><span>${fmt(m.voltage_v,2)} V</span></div>
          <div class="row"><span class="k">Current</span><span>${(m.current_a>=0?'+':'')}${fmt(m.current_a,1)} A</span></div>
          <div class="row"><span class="k">Health</span><span>${fmt(m.soh_pct,0)}%</span></div>
          <div class="row"><span class="k">Cell min/max</span><span>${fmt(m.min_cell_v,3)}/${fmt(m.max_cell_v,3)} V</span></div>
          <div class="row"><span class="k">Imbalance</span><span>${fmt(m.imbalance_mv,0)} mV</span></div>
          <div class="row"><span class="k">Temp</span><span>${fmt(m.min_temp_c,0)}–${fmt(m.max_temp_c,0)} °C</span></div>
          ${al?`<div class="fault">⚠ ${m.faults.join(', ')}</div>`:''}
        </div>`;
      }
      html += `</div></div>`;
    }
    $('#wrap').innerHTML = html;
    $('#foot').textContent = 'open-murata-bms · live view · refreshes every 1.5 s';
  } catch(e){ $('#sub').textContent = 'connection lost — retrying…'; }
}
tick(); setInterval(tick, 1500);
</script>
</body></html>
"""
