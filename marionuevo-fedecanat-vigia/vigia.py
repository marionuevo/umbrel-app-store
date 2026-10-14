"""Vigía Fedecanat: avisa cuando cambia una carpeta compartida de la federación.

Cada `intervalo_min` lista la carpeta del owncloud de la Federación Canaria de
Natación (WebDAV público, PROPFIND con Depth: infinity). Si aparece un archivo
o una carpeta, o cambia uno que ya estaba, llama al webhook de Home Assistant,
que manda el aviso al iPhone. Además sirve una página de estado en el puerto 8080.

Configuración en /data/config.json (no está en git). Estado en /data/estado.json.
"""
import base64, datetime as dt, html, json, os, re, threading, time, traceback
import urllib.parse, urllib.request
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATA = os.environ.get("VIGIA_DATA", "/data")
CONFIG, ESTADO = f"{DATA}/config.json", f"{DATA}/estado.json"
DAV = "/owncloud/public.php/webdav"
AVISO_FALLO_H = 3          # horas seguidas sin poder leer la carpeta antes de avisar
lock = threading.Lock()
despertar = threading.Event()


def cargar(ruta, defecto):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return defecto


def guardar(ruta, datos):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ruta)


def ahora():
    return dt.datetime.now(dt.timezone.utc)


def canarias(t):
    """Hora de Canarias: UTC+1 del último domingo de marzo al último de octubre (01:00 UTC)."""
    def ultimo_domingo(año, mes):
        d = dt.datetime(año, mes, 31 if mes in (3, 10) else 30, 1, tzinfo=dt.timezone.utc)
        return d - dt.timedelta(days=(d.weekday() + 1) % 7)
    verano = ultimo_domingo(t.year, 3) <= t < ultimo_domingo(t.year, 10)
    return t + dt.timedelta(hours=1 if verano else 0)


def fmt(iso):
    if not iso:
        return "—"
    return canarias(dt.datetime.fromisoformat(iso)).strftime("%d/%m/%Y %H:%M")


def listar(cfg):
    """Devuelve {ruta: {etag, mod, tam, carpeta}} de todo lo que cuelga de cfg['carpeta']."""
    base = cfg["servidor"].rstrip("/")
    carpeta = urllib.parse.quote(cfg["carpeta"])
    auth = base64.b64encode((cfg["share_token"] + ":").encode()).decode()
    req = urllib.request.Request(f"{base}{DAV}{carpeta}", method="PROPFIND",
                                 headers={"Depth": "infinity", "Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        xml = r.read().decode("utf-8")
    items = {}
    for resp in re.findall(r"<d:response>(.*?)</d:response>", xml, re.S):
        href = urllib.parse.unquote(re.search(r"<d:href>(.*?)</d:href>", resp).group(1))
        ruta = href.split(DAV, 1)[-1]
        def prop(nombre):
            m = re.search(rf"<d:{nombre}>(.*?)</d:{nombre}>", resp, re.S)
            return html.unescape(m.group(1)) if m else ""
        mod = prop("getlastmodified")
        items[ruta] = {
            "etag": prop("getetag").strip('"'),
            "mod": parsedate_to_datetime(mod).isoformat() if mod else "",
            "tam": int(prop("getcontentlength") or 0),
            "carpeta": "<d:collection" in resp,
        }
    return items


def avisar(cfg, titulo, mensaje, ruta=None):
    enlace = cfg["enlace"]
    if ruta:
        dir_ = ruta if ruta.endswith("/") else ruta.rsplit("/", 1)[0] + "/"
        enlace = f"{cfg['servidor'].rstrip('/')}/owncloud/index.php/s/{cfg['share_token']}?path=" + \
            urllib.parse.quote(dir_.rstrip("/") or "/", safe="")
    cuerpo = json.dumps({"title": titulo, "message": mensaje, "url": enlace}).encode()
    req = urllib.request.Request(cfg["webhook"], data=cuerpo, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()


def nombre(ruta):
    return ruta.rstrip("/").rsplit("/", 1)[-1]


def anotar(est, texto):
    est.setdefault("eventos", []).insert(0, {"t": ahora().isoformat(), "texto": texto})
    del est["eventos"][60:]


def comprobar():
    cfg = cargar(CONFIG, None)
    if not cfg:
        print(f"Falta {CONFIG}: ver README", flush=True)
        return
    with lock:
        est = cargar(ESTADO, {})
        est["ultima_comprobacion"] = ahora().isoformat()
        try:
            items = listar(cfg)
        except Exception as e:  # red caída, servidor fuera, enlace retirado...
            est["error"] = f"{type(e).__name__}: {e}"
            est.setdefault("fallando_desde", ahora().isoformat())
            desde = dt.datetime.fromisoformat(est["fallando_desde"])
            if ahora() - desde > dt.timedelta(hours=AVISO_FALLO_H) and not est.get("fallo_avisado"):
                try:
                    avisar(cfg, "Vigía Fedecanat", f"No puedo leer la carpeta de la federación desde las "
                           f"{fmt(est['fallando_desde'])[-5:]}. Último error: {est['error'][:120]}")
                    est["fallo_avisado"] = True
                    anotar(est, "Avisado: la carpeta lleva más de 3 h sin poder leerse")
                except Exception:
                    pass
            guardar(ESTADO, est)
            return
        if est.get("fallo_avisado"):
            try:
                avisar(cfg, "Vigía Fedecanat", "Vuelvo a leer la carpeta de la federación.")
            except Exception:
                pass
        for k in ("error", "fallando_desde", "fallo_avisado"):
            est.pop(k, None)

        antes = est.get("items")
        raiz = cfg["carpeta"]
        if antes is None:
            est["items"] = items
            n = sum(1 for i in items.values() if not i["carpeta"])
            anotar(est, f"Primera lectura: {n} archivo(s) en {raiz}")
            try:
                avisar(cfg, "Vigía Fedecanat activo",
                       f"Vigilo {raiz.strip('/')} cada {cfg['intervalo_min']} min. Ahora hay {n} archivo(s).")
            except Exception as e:
                anotar(est, f"No se pudo mandar el aviso de inicio: {e}")
            guardar(ESTADO, est)
            return

        nuevos = [r for r in items if r not in antes and r != raiz]
        cambiados = [r for r in items if r in antes and not items[r]["carpeta"]
                     and items[r]["etag"] != antes[r]["etag"]]
        borrados = [r for r in antes if r not in items]
        # Una carpeta nueva solo se cuenta si no trae archivos (si los trae, basta con avisar de ellos)
        nuevos_arch = [r for r in nuevos if not items[r]["carpeta"]]
        nuevas_carp = [r for r in nuevos if items[r]["carpeta"]
                       and not any(a.startswith(r) for a in nuevos_arch)]
        lineas = [f"Nuevo: {nombre(r)}" for r in nuevos_arch] + \
                 [f"Carpeta nueva: {nombre(r)}" for r in nuevas_carp] + \
                 [f"Actualizado: {nombre(r)}" for r in cambiados]
        for r in borrados:
            anotar(est, f"Retirado: {nombre(r)}")
        if lineas:
            primero = (nuevos_arch + nuevas_carp + cambiados)[0]
            sitio = nombre(primero.rstrip("/").rsplit("/", 1)[0] + "/") if not items[primero]["carpeta"] else raiz.strip("/")
            msg = "\n".join(lineas[:4]) + (f"\n… y {len(lineas) - 4} más" if len(lineas) > 4 else "") + f"\n({sitio})"
            try:
                avisar(cfg, "Fedecanat · " + raiz.strip("/").split("-", 1)[-1].title(), msg, primero)
                for l in lineas:
                    anotar(est, l + " — avisado")
                est["items"] = items
            except Exception as e:
                # Sin aviso no se da por visto: se reintenta en la próxima comprobación
                anotar(est, f"Cambios detectados pero el aviso falló ({e}); se reintentará")
                for r in borrados:
                    antes.pop(r, None)
                est["items"] = antes
        else:
            est["items"] = items
        guardar(ESTADO, est)


def bucle():
    while True:
        try:
            comprobar()
        except Exception:
            traceback.print_exc()
        cfg = cargar(CONFIG, {}) or {}
        despertar.wait(60 * int(cfg.get("intervalo_min", 15)) if cfg else 30)
        despertar.clear()


PAGINA = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Vigía Fedecanat</title>
<style>
:root{--bg:#f2f5f6;--fg:#10232b;--muted:#5b6f77;--line:#d6e0e3;--card:#fff;--accent:#0a6a8c;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#0c181c;--fg:#e3edf0;--muted:#8fa4ab;--line:#233940;--card:#122329;--accent:#55b9dc;--bad:#f2867c;color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,sans-serif}
main{max-width:820px;margin:0 auto;padding:24px 16px 48px;display:grid;gap:20px}
h1{margin:0;font-size:26px} h2{margin:0 0 8px;font-size:13px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.row{display:flex;flex-wrap:wrap;gap:8px 24px} .row div span{display:block;color:var(--muted);font-size:12px}
.bad{color:var(--bad)} table{width:100%%;border-collapse:collapse;font-variant-numeric:tabular-nums}
td{padding:6px 4px;border-top:1px solid var(--line);vertical-align:top} td.r{text-align:right;color:var(--muted);white-space:nowrap}
.dir td{font-weight:600} a{color:var(--accent)}
form{display:inline} button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:8px;padding:7px 12px;cursor:pointer}
.scroll{overflow-x:auto}
</style></head><body><main>
<div><h1>Vigía Fedecanat</h1><div style="color:var(--muted)">Vigila <b>%(carpeta)s</b> en el owncloud de la federación cada %(intervalo)s min y avisa al iPhone por Home Assistant.</div></div>
<div class="card row">
<div><span>Última comprobación</span>%(ultima)s</div>
<div><span>Estado</span>%(estado)s</div>
<div><span>Carpeta</span><a href="%(enlace)s" target="_blank" rel="noopener">abrir en la web</a></div>
</div>
<div class="row">
<form method="post" action="comprobar"><button>Comprobar ahora</button></form>
<form method="post" action="prueba"><button>Enviar aviso de prueba</button></form>
</div>
<div class="card"><h2>Contenido</h2><div class="scroll"><table>%(items)s</table></div></div>
<div class="card"><h2>Historial</h2><div class="scroll"><table>%(eventos)s</table></div></div>
</main></body></html>"""


class Web(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        cfg, est = cargar(CONFIG, {}), cargar(ESTADO, {})
        items = est.get("items") or {}
        filas = []
        for r in sorted(items):
            i = items[r]
            prof = r.strip("/").count("/") - cfg.get("carpeta", "/").strip("/").count("/")
            sangria = "&nbsp;" * 4 * max(prof - 1, 0)
            tam = f"{i['tam'] / 1024:.0f} KB" if not i["carpeta"] else ""
            filas.append(f"<tr class='{'dir' if i['carpeta'] else ''}'><td>{sangria}{html.escape(nombre(r) or r)}"
                         f"{'/' if i['carpeta'] else ''}</td><td class='r'>{tam}</td><td class='r'>{fmt(i['mod'])}</td></tr>")
        eventos = [f"<tr><td class='r'>{fmt(e['t'])}</td><td>{html.escape(e['texto'])}</td></tr>"
                   for e in est.get("eventos", [])]
        estado = "Correcto" if not est.get("error") else \
            f"<span class='bad'>Sin poder leer desde {fmt(est.get('fallando_desde'))}: {html.escape(est['error'][:200])}</span>"
        cuerpo = PAGINA % {
            "carpeta": html.escape(cfg.get("carpeta", "")), "intervalo": cfg.get("intervalo_min", 15),
            "ultima": fmt(est.get("ultima_comprobacion")), "estado": estado,
            "enlace": html.escape(cfg.get("enlace", "#")),
            "items": "".join(filas) or "<tr><td>Todavía sin leer.</td></tr>",
            "eventos": "".join(eventos) or "<tr><td>Sin eventos.</td></tr>",
        }
        self._responder(200, cuerpo)

    def do_POST(self):
        if self.path.endswith("/comprobar"):
            despertar.set()
            time.sleep(3)
        elif self.path.endswith("/prueba"):
            cfg = cargar(CONFIG, {})
            with lock:
                est = cargar(ESTADO, {})
                try:
                    avisar(cfg, "Vigía Fedecanat", "Aviso de prueba: el vigilante y Home Assistant se hablan bien.")
                    anotar(est, "Aviso de prueba enviado")
                except Exception as e:
                    anotar(est, f"El aviso de prueba falló: {e}")
                guardar(ESTADO, est)
        self.send_response(303)
        self.send_header("Location", "./")
        self.end_headers()

    def _responder(self, código, cuerpo):
        datos = cuerpo.encode()
        self.send_response(código)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)


if __name__ == "__main__":
    threading.Thread(target=bucle, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8080), Web).serve_forever()
