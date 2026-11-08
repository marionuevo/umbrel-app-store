"""Tiempos de natación: historial de marcas de una nadadora.

- Guarda una lista de nadadas (una fila por prueba nadada) en /data/nadadas.json.
- Cada `intervalo_min` busca PDF de resultados nuevos (Splash Meet Manager) en el
  owncloud público de la federación, saca las nadadas de los nombres configurados
  y avisa por un webhook de Home Assistant.
- Sirve una web en el puerto 8080: mejores marcas por piscina, evolución, historial,
  ritmo por parciales y alta o corrección a mano.

Configuración en /data/config.json (no está en git: lleva nombres y el webhook).
Uso local para probar el lector: python3 tiempos.py --leer resultados.pdf "APELLIDOS, N"
"""
import base64, csv, datetime as dt, html, io, json, os, re, subprocess, sys, tempfile
import threading, time, traceback, urllib.parse, urllib.request, uuid
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATA = os.environ.get("TIEMPOS_DATA", "/data")
WWW = os.environ.get("TIEMPOS_WWW", os.path.join(os.path.dirname(os.path.abspath(__file__)), "www"))
CONFIG = f"{DATA}/config.json"
NADADAS = f"{DATA}/nadadas.json"
PAPELERA = f"{DATA}/papelera.json"
ESTADO = f"{DATA}/estado.json"
DAV = "/owncloud/public.php/webdav"
DEFECTO = {
    "nombre": "",
    "patrones": [],
    "servidor": "http://fedecanat.es",
    "share_token": "",
    "carpetas": ["/1-GRAN CANARIA/", "/2-TENERIFE/", "/3-LANZAROTE-FUERTEVENTURA/",
                 "/CAMPEONATO REGIONALES/", "/CIRCUITO DE NATACIÓN/", "/COPA DE CLUBS/"],
    "intervalo_min": 30,
    "webhook": "",
    "url_app": "",
    "sexo": "f",
}
# Tiempos base de los puntos de World Aquatics (AQUA): P = 1000 × (B / T)³, truncado.
# Piscina de 25 m: tabla SCM 2026 (válida del 01.09.2026 al 31.08.2027); de 50 m: LCM 2026
# (01.01.2026 – 31.12.2026). Fuente: Points-Base-times-SCM-and-LCM-2026_09.2026.pdf en
# worldaquatics.com/swimming/points. Comprobadas con los puntos de los PDF de Splash de la temporada.
BASES = {
    ("f", 25): {"50 libre": 22.83, "100 libre": 49.93, "200 libre": 109.36, "400 libre": 230.25, "800 libre": 474.0, "1500 libre": 908.24, "50 espalda": 25.23, "100 espalda": 54.02, "200 espalda": 117.33, "50 braza": 28.37, "100 braza": 62.36, "200 braza": 132.5, "50 mariposa": 23.72, "100 mariposa": 52.71, "200 mariposa": 119.32, "100 estilos": 55.11, "200 estilos": 121.63, "400 estilos": 255.48},
    ("f", 50): {"50 libre": 23.61, "100 libre": 51.71, "200 libre": 112.23, "400 libre": 234.18, "800 libre": 484.12, "1500 libre": 920.48, "50 espalda": 26.86, "100 espalda": 57.13, "200 espalda": 123.14, "50 braza": 29.16, "100 braza": 64.13, "200 braza": 137.55, "50 mariposa": 24.43, "100 mariposa": 54.6, "200 mariposa": 121.81, "200 estilos": 125.7, "400 estilos": 263.65},
    ("m", 25): {"50 libre": 19.9, "100 libre": 44.84, "200 libre": 98.61, "400 libre": 212.25, "800 libre": 440.46, "1500 libre": 846.88, "50 espalda": 22.11, "100 espalda": 48.16, "200 espalda": 105.12, "50 braza": 24.95, "100 braza": 55.28, "200 braza": 119.52, "50 mariposa": 21.32, "100 mariposa": 47.68, "200 mariposa": 106.85, "100 estilos": 49.28, "200 estilos": 108.88, "400 estilos": 234.81},
    ("m", 50): {"50 libre": 20.91, "100 libre": 46.4, "200 libre": 102.0, "400 libre": 219.96, "800 libre": 452.12, "1500 libre": 870.67, "50 espalda": 23.55, "100 espalda": 51.6, "200 espalda": 111.92, "50 braza": 25.95, "100 braza": 56.88, "200 braza": 125.48, "50 mariposa": 22.27, "100 mariposa": 49.45, "200 mariposa": 110.34, "200 estilos": 112.69, "400 estilos": 242.5},
}
lock = threading.Lock()
despertar = threading.Event()


# ---------------------------------------------------------------- archivos

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


def config():
    cfg = dict(DEFECTO)
    cfg.update(cargar(CONFIG, {}))
    return cfg


def ahora():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- lector de PDF de Splash

TIEMPO = r"(?:\d{1,2}:)?\d{1,2}\.\d{2}"
RE_PRUEBA = re.compile(
    r"^\s*Prueba\s+(\d+)\s*,?\s+(Fem|Masc|Mixto|Mix)\.?,?\s+(\d+)\s*m\s+"
    r"(Libre|Espalda|Braza|Mariposa|Estilos)\b,?\s*(.*?)\s*$", re.I)
RE_CATEGORIA = re.compile(
    r"^\s{2,}((?:Infantil|J[uú]nior|Absolut[oa]|Alev[ií]n|Benjam[ií]n|Prebenjam[ií]n|Senior|"
    r"M[aá]ster|Open)\b[^\d:]*?)\s*$", re.I)
RE_FECHA = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\b")
RE_CIUDAD = re.compile(r"^(.+?),\s*(\d{1,2})/(\d{1,2})/(\d{4})$")
ESTADOS = {"DSQ": "dsq", "DQ": "dsq", "DESC": "dsq", "NP": None, "BAJA": None, "RET": None,
           "DNS": None, "DNF": None}
PLANO = str.maketrans("ÁÉÍÓÚÜÑáéíóúüñ", "AEIOUUNAEIOUUN")


def segundos(t):
    p = t.split(":")
    return round(int(p[0]) * 60 + float(p[1]), 2) if len(p) == 2 else round(float(p[0]), 2)


def iso(d, m, a):
    return f"{int(a):04d}-{int(m):02d}-{int(d):02d}"


def normal(s):
    return s.translate(PLANO).upper()


def pdf_a_texto(ruta):
    r = subprocess.run(["pdftotext", "-layout", ruta, "-"], capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip() or "pdftotext falló")
    return r.stdout.decode("utf-8", "replace")


def leer_resultados(texto, patrones):
    """Nadadas de los nombres de `patrones` en el texto de un PDF de resultados de Splash.

    Cada nadada sale una vez por prueba; si el PDF la lista en varias clasificaciones
    (por categoría y absoluta), los puestos extra van en `puestos`.
    """
    pats = [normal(p).strip() for p in patrones if p.strip()]
    comp = ciudad = fecha_pag = None
    ev = cat = None
    ultimo_puesto = None
    salida = {}
    for pagina in texto.split("\f"):
        lineas = pagina.split("\n")
        visibles = [l.strip() for l in lineas if l.strip()]
        if visibles and comp is None:
            comp = visibles[0]
        for l in visibles[:3]:
            m = RE_CIUDAD.match(l)
            if m:
                ciudad, fecha_pag = m.group(1), iso(m.group(2), m.group(3), m.group(4))
        for i, l in enumerate(lineas):
            if re.match(r"^\s*Prueba\s+\d+", l):
                m = RE_PRUEBA.match(l)
                if not m:
                    ev = None          # relevos u otras pruebas que no son individuales
                    continue
                num = int(m.group(1))
                resto = m.group(5)
                if ev is None or ev["num"] != num:
                    ev = {"num": num, "distancia": int(m.group(3)), "estilo": m.group(4).lower(),
                          "sexo": m.group(2).lower()[:1], "fecha": fecha_pag}
                # «Prueba 1, Fem., 400m Libre, Absoluta Femenina»: la categoría va al final
                cat = resto.split("  ")[0].strip() if "," in l[:30] and resto else None
                ultimo_puesto = None
                continue
            if ev is None:
                continue
            mf = RE_FECHA.match(l)
            if mf and "Resultados" in l:
                ev["fecha"] = iso(mf.group(1), mf.group(2), mf.group(3))
                continue
            mc = RE_CATEGORIA.match(l)
            if mc:
                cat = mc.group(1).strip()
                continue
            mp = re.match(r"^\s*(\d+)\.", l)
            if mp:
                ultimo_puesto = int(mp.group(1))
            nl = normal(l)
            pos = next((nl.find(p) + len(p) for p in pats if p in nl), -1)
            if pos < 0:
                continue
            ms = re.match(r"^\s*(?:(\d+)\.|([A-Z]{2,4})\b)?", l)
            estado = ESTADOS.get(ms.group(2) or "", "x") if ms.group(2) else "x"
            if estado is None:
                continue                # no presentada, baja o retirada
            cola = l[pos:]
            tiempos = re.findall(rf"(?<![\d:.,]){TIEMPO}(?![\d,])", cola)
            if estado == "x" and not tiempos:
                continue
            puntos = re.search(r"\s(\d{1,4})\s*$", cola)
            puesto = int(ms.group(1)) if ms.group(1) else (None if estado == "dsq" else ultimo_puesto)
            parciales = {}
            nota = ""
            for sig in lineas[i + 1:i + 12]:
                pares = re.findall(rf"(\d+)m:\s+({TIEMPO})", sig)
                if pares:
                    for d, t in pares:
                        parciales[int(d)] = segundos(t)
                elif estado == "dsq" and sig.strip() and not nota and (
                        re.match(r"^\s*[A-Z0-9]{2,5}\s*-\s", sig) or not re.match(r"^\s*(\d+\.|[A-Z]{2,4}\s)", sig)):
                    nota = re.sub(r"\s{2,}", " ", sig.strip())
                    break
                else:
                    break
            clave = ev["num"]
            if clave in salida:
                if puesto and cat:
                    salida[clave]["puestos"].append([puesto, cat])
                continue
            t = segundos(tiempos[0]) if estado == "x" else None
            salida[clave] = {
                "fecha": ev["fecha"] or fecha_pag, "competicion": comp, "ciudad": ciudad,
                "prueba_num": ev["num"], "distancia": ev["distancia"], "estilo": ev["estilo"],
                "tiempo": t, "tipo": "oficial" if estado == "x" else "dsq",
                "puesto": puesto, "categoria": cat, "puestos": [[puesto, cat]] if puesto else [],
                "puntos": int(puntos.group(1)) if puntos and estado == "x" else None,
                "parciales": sorted([d, v] for d, v in parciales.items()) if t else [],
                "nota": nota,
            }
    out = list(salida.values())
    for n in out:   # los parciales tienen que acabar en la marca final; si no, fuera
        if n["parciales"] and abs(n["parciales"][-1][1] - n["tiempo"]) > 0.02:
            n["parciales"] = []
    return out


def piscina_en_textos(textos):
    """Busca la longitud de la piscina de competición en las bases o el INFO de la competición."""
    for t in textos:
        m = re.search(r"piscina[^\n]{0,80}?\b(25|50)\s*(?:m\b|metros)", t, re.I) or \
            re.search(r"\b(25|50)\s*(?:m|metros)\s+y\s+\d+\s+calles", t, re.I)
        if m:
            return int(m.group(1))
    return None


# ---------------------------------------------------------------- owncloud

def _auth(cfg):
    return "Basic " + base64.b64encode((cfg["share_token"] + ":").encode()).decode()


def listar(cfg, carpeta):
    url = cfg["servidor"].rstrip("/") + DAV + urllib.parse.quote(carpeta)
    req = urllib.request.Request(url, method="PROPFIND",
                                 headers={"Depth": "infinity", "Authorization": _auth(cfg)})
    with urllib.request.urlopen(req, timeout=120) as r:
        xml = r.read().decode("utf-8")
    items = {}
    for resp in re.findall(r"<d:response>(.*?)</d:response>", xml, re.S):
        href = urllib.parse.unquote(re.search(r"<d:href>(.*?)</d:href>", resp).group(1))
        ruta = href.split(DAV, 1)[-1]
        if "<d:collection" in resp:
            continue
        et = re.search(r"<d:getetag>(.*?)</d:getetag>", resp, re.S)
        mod = re.search(r"<d:getlastmodified>(.*?)</d:getlastmodified>", resp, re.S)
        items[ruta] = {"etag": html.unescape(et.group(1)).strip('"') if et else "",
                       "mod": parsedate_to_datetime(mod.group(1)).isoformat() if mod else ""}
    return items


def descargar_texto(cfg, ruta):
    url = cfg["servidor"].rstrip("/") + DAV + urllib.parse.quote(ruta)
    req = urllib.request.Request(url, headers={"Authorization": _auth(cfg)})
    with urllib.request.urlopen(req, timeout=120) as r, \
            tempfile.NamedTemporaryFile(suffix=".pdf", dir="/tmp", delete=False) as f:
        f.write(r.read())
        tmp = f.name
    try:
        return pdf_a_texto(tmp)
    finally:
        os.replace(tmp, tmp + ".leido")   # /tmp del contenedor: se vacía al reiniciar


def enlace_carpeta(cfg, ruta):
    d = ruta.rsplit("/", 1)[0] or "/"
    return f"{cfg['servidor'].rstrip('/')}/owncloud/index.php/s/{cfg['share_token']}?path=" + \
        urllib.parse.quote(d, safe="")


def avisar(cfg, titulo, mensaje):
    if not cfg.get("webhook"):
        return
    cuerpo = json.dumps({"title": titulo, "message": mensaje, "url": cfg.get("url_app") or ""}).encode()
    req = urllib.request.Request(cfg["webhook"], data=cuerpo, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()


# ---------------------------------------------------------------- nadadas

def etiqueta(n):
    return f"{n['distancia']} {n['estilo']}"


def fmt(t):
    if t is None:
        return "—"
    if t < 60:
        return f"{t:.2f}"
    m = int(t // 60)
    return f"{m}:{t - m * 60:05.2f}"


def puntos(n, sexo):
    """Puntos AQUA con las tablas vigentes (las mismas para todas las fechas, para poder comparar)."""
    b = BASES.get((sexo, n.get("piscina") or 0), {}).get(etiqueta(n))
    t = n.get("tiempo")
    return int(1000 * (b / t) ** 3) if b and t else None


def equivalencias(n, sexo):
    """Tiempo equivalente en cada piscina: el que da los mismos puntos AQUA."""
    b = BASES.get((sexo, n.get("piscina") or 0), {}).get(etiqueta(n))
    t = n.get("tiempo")
    if not b or not t:
        return {}
    out = {}
    for p in (25, 50):
        bp = BASES.get((sexo, p), {}).get(etiqueta(n))
        if bp:
            out[str(p)] = round(t * bp / b, 2)
    return out


def es_mejor(lista, n):
    """¿Es `n` la mejor marca oficial de su prueba y piscina hasta su fecha?"""
    if n.get("tipo") != "oficial" or n.get("tiempo") is None or not n.get("piscina") or n.get("a_mano"):
        return False
    antes = [x["tiempo"] for x in lista if x is not n and x.get("tipo") == "oficial" and not x.get("a_mano")
             and x.get("tiempo") is not None and x.get("piscina") == n["piscina"]
             and x["distancia"] == n["distancia"] and x["estilo"] == n["estilo"]
             and str(x.get("fecha") or "") <= str(n.get("fecha") or "")]
    return not antes or n["tiempo"] < min(antes)


def incorporar(lista, leidas, ruta, piscina):
    """Añade o actualiza las nadadas leídas de un PDF. Devuelve las nuevas."""
    nuevas = []
    for e in leidas:
        previa = next((x for x in lista if x.get("origen") == ruta
                       and x.get("prueba_num") == e["prueba_num"]), None)
        if previa is None:
            previa = next((x for x in lista if x.get("fecha") == e["fecha"]
                           and x["distancia"] == e["distancia"] and x["estilo"] == e["estilo"]
                           and x.get("tiempo") == e["tiempo"]), None)
            if previa is not None:      # ya estaba (otro PDF de la misma prueba o alta manual)
                if not previa.get("parciales") and e["parciales"]:
                    previa["parciales"] = e["parciales"]
                continue
            n = dict(e, id=uuid.uuid4().hex[:12], origen=ruta, piscina=piscina,
                     piscina_auto=piscina is not None, añadida=ahora())
            lista.append(n)
            nuevas.append(n)
        else:                           # resultados corregidos (provisionales → definitivos)
            for k in ("tiempo", "tipo", "puesto", "categoria", "puestos", "puntos", "parciales",
                      "fecha", "competicion", "ciudad", "nota"):
                if previa.get("a_mano") and k in ("tiempo", "parciales", "nota"):
                    continue        # el tiempo tomado a mano no lo trae la federación
                previa[k] = e[k]
    return nuevas


# ---------------------------------------------------------------- búsqueda periódica

def anotar(est, texto):
    est.setdefault("eventos", []).insert(0, {"t": ahora(), "texto": texto})
    del est["eventos"][40:]


def buscar():
    cfg = config()
    est = cargar(ESTADO, {})
    if not cfg["share_token"] or not cfg["patrones"]:
        est["error"] = "Falta share_token o patrones en config.json"
        guardar(ESTADO, est)
        return
    revisados = est.setdefault("revisados", {})
    est["buscando"] = True
    guardar(ESTADO, est)
    errores = []
    for carpeta in cfg["carpetas"]:
        try:
            items = listar(cfg, carpeta)
        except Exception as e:
            errores.append(f"{carpeta}: {e}")
            continue
        for ruta, it in sorted(items.items()):
            if not ruta.lower().endswith(".pdf") or not re.search(r"result", ruta.rsplit("/", 1)[-1], re.I):
                continue
            if revisados.get(ruta, {}).get("etag") == it["etag"]:
                continue
            try:
                leidas = leer_resultados(descargar_texto(cfg, ruta), cfg["patrones"])
                nuevas = []
                if leidas:
                    d = ruta.rsplit("/", 1)[0] + "/"
                    bases = [r for r in items if r.startswith(d) and r.lower().endswith(".pdf")
                             and re.search(r"info|instruc|normativ|convocatoria|bases", r.rsplit("/", 1)[-1], re.I)]
                    textos = []
                    for b in bases[:4]:
                        try:
                            textos.append(descargar_texto(cfg, b))
                        except Exception:
                            pass
                    piscina = piscina_en_textos(textos)
                    with lock:
                        lista = cargar(NADADAS, [])
                        nuevas = incorporar(lista, leidas, ruta, piscina)
                        guardar(NADADAS, lista)
                    if nuevas:
                        partes = []
                        for n in nuevas:
                            txt = f"{etiqueta(n)} {fmt(n['tiempo'])}" if n["tiempo"] else f"{etiqueta(n)} descalificada"
                            if es_mejor(lista, n):
                                txt += ", mejor marca"
                            partes.append(txt)
                        anotar(est, f"{len(nuevas)} nadada(s) nueva(s) en {ruta.rsplit('/', 1)[-1]}")
                        try:
                            avisar(cfg, f"Resultados de {cfg['nombre'] or 'la nadadora'}", ". ".join(partes) + ".")
                        except Exception as e:
                            errores.append(f"aviso: {e}")
                revisados[ruta] = {"etag": it["etag"], "t": ahora(), "n": len(leidas)}
            except Exception as e:
                errores.append(f"{ruta}: {e}")
            guardar(ESTADO, est)
    est["buscando"] = False
    est["ultima"] = ahora()
    est["error"] = "; ".join(errores)[:600]
    if errores:
        anotar(est, "Errores en la búsqueda: " + est["error"][:200])
    guardar(ESTADO, est)


def bucle():
    while True:
        try:
            buscar()
        except Exception:
            traceback.print_exc()
        despertar.wait(max(5, config()["intervalo_min"]) * 60)
        despertar.clear()


# ---------------------------------------------------------------- web

CAMPOS = {"fecha": str, "competicion": str, "ciudad": str, "piscina": int, "distancia": int,
          "estilo": str, "tiempo": float, "tipo": str, "puesto": int, "nota": str, "a_mano": bool}


def limpiar(d):
    out = {}
    for k, tipo in CAMPOS.items():
        if k not in d:
            continue
        v = d[k]
        if tipo is bool:
            out[k] = v in (True, "true", "on", "1", 1)
        else:
            out[k] = None if v in (None, "") else tipo(v)
    if out.get("estilo") and out["estilo"] not in ("libre", "espalda", "braza", "mariposa", "estilos"):
        raise ValueError("estilo no válido")
    if out.get("tipo") and out["tipo"] not in ("oficial", "parcial", "relevo", "dsq"):
        raise ValueError("tipo no válido")
    if out.get("piscina") not in (None, 25, 50):
        raise ValueError("la piscina es de 25 o de 50 m")
    return out


class Web(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, codigo, datos):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        ruta = urllib.parse.urlparse(self.path).path
        if ruta in ("/", "/index.html"):
            with open(os.path.join(WWW, "index.html"), "rb") as f:
                cuerpo = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(cuerpo)
        elif ruta == "/api/datos":
            cfg = config()
            est = cargar(ESTADO, {})
            nadadas = cargar(NADADAS, [])
            for n in nadadas:
                n["_pts"] = puntos(n, cfg["sexo"])
                n["_eq"] = equivalencias(n, cfg["sexo"])
            self._json(200, {
                "nombre": cfg["nombre"], "nadadas": nadadas,
                "papelera": len(cargar(PAPELERA, [])),
                "estado": {k: est.get(k) for k in ("ultima", "buscando", "error", "eventos")}
                | {"revisados": len(est.get("revisados", {})), "intervalo_min": cfg["intervalo_min"]},
            })
        elif ruta == "/api/csv":
            buf = io.StringIO()
            w = csv.writer(buf, delimiter=";")
            cols = ["fecha", "competicion", "ciudad", "piscina", "distancia", "estilo", "tiempo",
                    "tipo", "a_mano", "puesto", "categoria", "puntos", "nota", "origen"]
            w.writerow(cols + ["tiempo_texto"])
            for n in sorted(cargar(NADADAS, []), key=lambda x: str(x.get("fecha") or "")):
                w.writerow([n.get(c) if n.get(c) is not None else "" for c in cols] + [fmt(n.get("tiempo"))])
            # «puntos» es el dato del PDF; los puntos AQUA calculados van en la web
            cuerpo = ("\ufeff" + buf.getvalue()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="tiempos.csv"')
            self.end_headers()
            self.wfile.write(cuerpo)
        else:
            self._json(404, {"error": "no existe"})

    def do_POST(self):
        ruta = urllib.parse.urlparse(self.path).path
        try:
            largo = int(self.headers.get("Content-Length") or 0)
            datos = json.loads(self.rfile.read(largo) or b"{}")
            with lock:
                lista = cargar(NADADAS, [])
                if ruta == "/api/nadada":
                    campos = limpiar(datos)
                    if datos.get("id"):
                        n = next((x for x in lista if x["id"] == datos["id"]), None)
                        if n is None:
                            return self._json(404, {"error": "No encuentro esa nadada"})
                        if "piscina" in campos and campos["piscina"] != n.get("piscina"):
                            n["piscina_auto"] = False
                        n.update(campos)
                    else:
                        for k in ("fecha", "distancia", "estilo", "tipo"):
                            if not campos.get(k):
                                return self._json(400, {"error": f"Falta {k}"})
                        n = dict(campos, id=uuid.uuid4().hex[:12], origen="manual", añadida=ahora(),
                                 parciales=[], puestos=[])
                        lista.append(n)
                    guardar(NADADAS, lista)
                    return self._json(200, {"ok": True, "nadada": n})
                if ruta == "/api/papelera":
                    n = next((x for x in lista if x["id"] == datos.get("id")), None)
                    if n is None:
                        return self._json(404, {"error": "No encuentro esa nadada"})
                    pap = cargar(PAPELERA, [])
                    pap.append(dict(n, borrada=ahora()))
                    guardar(PAPELERA, pap)
                    lista.remove(n)
                    guardar(NADADAS, lista)
                    return self._json(200, {"ok": True})
                if ruta == "/api/restaurar":
                    pap = cargar(PAPELERA, [])
                    if not pap:
                        return self._json(404, {"error": "La papelera está vacía"})
                    n = pap.pop()
                    n.pop("borrada", None)
                    lista.append(n)
                    guardar(NADADAS, lista)
                    guardar(PAPELERA, pap)
                    return self._json(200, {"ok": True, "nadada": n})
                if ruta == "/api/competicion":
                    piscina = limpiar({"piscina": datos.get("piscina")}).get("piscina")
                    k = 0
                    for x in lista:
                        if x.get("competicion") == datos.get("competicion") and x.get("fecha") == datos.get("fecha"):
                            x["piscina"], x["piscina_auto"] = piscina, False
                            k += 1
                    guardar(NADADAS, lista)
                    return self._json(200, {"ok": True, "cambiadas": k})
            if ruta == "/api/buscar":
                despertar.set()
                return self._json(200, {"ok": True})
            self._json(404, {"error": "no existe"})
        except (ValueError, TypeError) as e:
            self._json(400, {"error": str(e)})


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == "--leer":
        print(json.dumps(leer_resultados(pdf_a_texto(sys.argv[2]), sys.argv[3:]), ensure_ascii=False, indent=1))
        return
    os.makedirs(DATA, exist_ok=True)
    est = cargar(ESTADO, {})
    est["buscando"] = False
    guardar(ESTADO, est)
    threading.Thread(target=bucle, daemon=True).start()
    puerto = int(os.environ.get("TIEMPOS_PUERTO", "8080"))
    print(f"Tiempos de natación en :{puerto}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", puerto), Web).serve_forever()


if __name__ == "__main__":
    main()
