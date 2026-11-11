"""Kleine statuspagina (alleen lezen) met de details achter het schermpje.

Draait in een aparte thread op STATUS_PORT. Toont per bron de laatste waarde,
alle beschikbare updates met namen, en fouten. Ververst zichzelf elke minuut.
"""
import html
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATUS = {"bronnen": {}, "updates": None, "wordpress": None, "gestart": None}
_lock = threading.Lock()


def zet(sleutel, waarde):
    with _lock:
        STATUS[sleutel] = waarde


def _e(x):
    return html.escape(str(x))


def _lijst(items, leeg="geen"):
    if not items:
        return f'<p class="ok">{_e(leeg)}</p>'
    return "<ul>" + "".join(f"<li>{_e(i)}</li>" for i in items) + "</ul>"


def _pagina():
    with _lock:
        s = json.loads(json.dumps(STATUS, default=str))
    rijen = []
    for naam, b in sorted(s["bronnen"].items()):
        klasse = "fout" if b.get("fout") else ("oud" if b.get("stale") else "")
        waarde = b.get("waarde")
        if isinstance(waarde, dict):
            waarde = ", ".join(f"{k}: {v}" for k, v in waarde.items()
                               if k not in ("sites", "errors", "docker", "compose", "plugins", "core", "themes"))
        rijen.append(
            f'<tr class="{klasse}"><td>{_e(naam)}</td><td>{_e(waarde if waarde is not None else "–")}</td>'
            f'<td>{_e(b.get("bijgewerkt") or "nog niet")}</td><td>{_e(b.get("fout") or "")}</td></tr>'
        )

    u = s.get("updates") or {}
    unraid = (
        "<h2>Unraid</h2>"
        f"<h3>Dockers</h3>{_lijst(u.get('docker'))}"
        f"<h3>Compose</h3>{_lijst(u.get('compose'))}"
        f"<h3>Plugins</h3>{_lijst(u.get('plugins'))}"
        f"<h3>Unraid zelf</h3>"
        + (f'<p class="fout">nieuwe versie: {_e(u["os"])}</p>' if u.get("os") else '<p class="ok">actueel</p>')
        + (f"<h3>Meldingen</h3>{_lijst(u.get('errors'))}" if u.get("errors") else "")
    )

    wp = s.get("wordpress") or {}
    sites = []
    for naam, info in sorted((wp.get("sites") or {}).items()):
        delen = []
        if info.get("core"):
            delen.append(f'<p class="fout">WordPress → {_e(info["core"])}</p>')
        if info.get("plugins"):
            delen.append("<p>Plugins:</p>" + _lijst(info["plugins"]))
        if info.get("themes"):
            delen.append("<p>Thema's:</p>" + _lijst(info["themes"]))
        if info.get("error"):
            delen.append(f'<p class="fout">fout: {_e(info["error"])}</p>')
        inhoud = "".join(delen) or '<p class="ok">alles actueel</p>'
        sites.append(f'<div class="site"><h3>{_e(naam)} <small>{_e(info.get("path"))}</small></h3>{inhoud}</div>')
    wordpress = "<h2>WordPress</h2>" + ("".join(sites) if sites else "<p>nog geen gegevens</p>")

    return f"""<!DOCTYPE html>
<html lang="nl"><head><meta charset="utf-8"><meta http-equiv="refresh" content="60">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GeekMagic-dashboard</title>
<style>
body{{font-family:system-ui,sans-serif;background:#1b1714;color:#f5ede4;max-width:900px;margin:2em auto;padding:0 1em}}
h1{{color:#FFD71B}} h2{{color:#FFD71B;border-bottom:1px solid #444;padding-bottom:.2em;margin-top:1.6em}}
h3{{margin:.8em 0 .2em}} small{{color:#a89a8c;font-weight:normal}}
table{{width:100%;border-collapse:collapse}} td,th{{text-align:left;padding:.35em .5em;border-bottom:1px solid #333;vertical-align:top}}
th{{color:#a89a8c;font-weight:normal}} .fout{{color:#e5533d}} .oud td{{color:#e5a03d}} .ok{{color:#7cc576}}
.site{{background:#28221d;border-radius:8px;padding:.4em 1em;margin:.6em 0}} ul{{margin:.2em 0}}
</style></head><body>
<h1>GeekMagic-dashboard</h1>
<p><small>gestart {_e(s.get("gestart") or "")} · ververst elke minuut</small></p>
<h2>Bronnen</h2>
<table><tr><th>Bron</th><th>Waarde</th><th>Bijgewerkt</th><th>Fout</th></tr>{"".join(rijen)}</table>
{unraid}
{wordpress}
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/json"):
            with _lock:
                body = json.dumps(STATUS, default=str, ensure_ascii=False, indent=1).encode()
            ctype = "application/json; charset=utf-8"
        else:
            body = _pagina().encode()
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def start(poort: int):
    srv = ThreadingHTTPServer(("0.0.0.0", poort), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
