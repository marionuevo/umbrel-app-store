"""Guía de jornada: línea de tiempo de una competición de natación y avisos por audio.

- Lee la jornada (pruebas, series y calles) de /data/jornada.json.
- Estima a qué hora empieza cada serie a partir de un ancla: «la serie i empezó en el
  instante t». Sin ancla, la primera serie empieza a la hora oficial de inicio.
  Desde la web se recoloca el marcador y el ancla se guarda en /data/estado.json.
- Cada 10 s mira qué series con nadadores de interés están a punto de empezar y
  llama al webhook de Home Assistant, que manda un aviso urgente al iPhone; Siri
  lo lee por los AirPods.
- Sirve la web (www/index.html) y una API JSON en el puerto 8080.

Configuración en /data/config.json (no está en git: lleva datos personales y el webhook).
"""
import datetime as dt, json, os, re, threading, time, traceback, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATA = os.environ.get("GUIA_DATA", "/data")
WWW = os.environ.get("GUIA_WWW", "/app/www")
CONFIG, JORNADA, ESTADO = f"{DATA}/config.json", f"{DATA}/jornada.json", f"{DATA}/estado.json"
lock = threading.RLock()
PARTICULAS = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "SAN"}


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


def ahora_ms():
    return int(time.time() * 1000)


# ---------- nombres para el audio ----------

def _capital(w):
    return w.lower() if w in PARTICULAS else "-".join(p.capitalize() for p in w.split("-"))


def _apellidos(ap):
    """Divide los apellidos en unidades; las partículas van con la palabra siguiente."""
    unidades, cur = [], []
    for w in ap.split():
        cur.append(w)
        if w not in PARTICULAS:
            unidades.append(cur)
            cur = []
    if cur:
        unidades.append(cur)
    return unidades


def nombres_cortos(todos):
    """{nombre completo: «Nombre Apellido»}; si dos coinciden, se añade el segundo apellido."""
    def corto(full, con_segundo=False):
        if ", " not in full:  # relevos: «Relevo», sin apellidos
            return full
        ap, _, nom = full.partition(", ")
        u = _apellidos(ap)
        primero = u[:-1] if len(u) > 2 else u[:1]
        palabras = [w for x in primero for w in x]
        if con_segundo and len(u) > len(primero):
            palabras += [w for x in u[len(primero):] for w in x]
        s = " ".join(_capital(w) for w in palabras)
        s = s[:1].upper() + s[1:]
        return f"{nom.split()[0] if nom else ''} {s}".strip()
    base = {n: corto(n) for n in todos}
    vistos = {}
    for n, c in base.items():
        vistos.setdefault(c, []).append(n)
    for c, ns in vistos.items():
        if len(ns) > 1:
            for n in ns:
                base[n] = corto(n, True)
    return base


def club_corto(cfg, club):
    alias = cfg.get("alias_clubes", {})
    if club in alias:
        return alias[club]
    return re.sub(r"^(C\.?N\.?|C\.?D\.?|A\.?D\.?|R\.?C\.?|Cdn|C\.D\. N\.)\s+", "", club).strip()


# ---------- horario ----------

def series_planas(jor):
    plano = []
    pruebas = jor["pruebas"]
    for pi, p in enumerate(pruebas):
        for s in p["series"]:
            ultima = s["n"] == len(p["series"]) and pi < len(pruebas) - 1
            plano.append({"id": f"P{p['n']}S{s['n']}", "p": p["n"], "s": s["n"], "ns": len(p["series"]),
                          "dur": s["duracion_s"], "pausa": p.get("pausa_s", 0) if ultima else 0,
                          "prueba": p, "serie": s})
    return plano


def inicio_oficial_ms(jor):
    return int(dt.datetime.fromisoformat(jor["jornada"]["inicio"].replace("Z", "+00:00")).timestamp() * 1000)


def horario(plano, jor, ancla):
    """Hora de inicio estimada (ms) de cada serie a partir del ancla."""
    i0, t0 = (ancla["i"], ancla["t"]) if ancla else (0, inicio_oficial_ms(jor))
    i0 = max(0, min(i0, len(plano) - 1))
    ini = [0] * len(plano)
    ini[i0] = t0
    for i in range(i0 + 1, len(plano)):
        ini[i] = ini[i - 1] + 1000 * (plano[i - 1]["dur"] + plano[i - 1]["pausa"])
    for i in range(i0 - 1, -1, -1):
        ini[i] = ini[i + 1] - 1000 * (plano[i]["dur"] + plano[i]["pausa"])
    return ini


def serie_actual(ini, t):
    actual = -1
    for i, x in enumerate(ini):
        if x <= t:
            actual = i
    return actual


# ---------- interés y avisos ----------

def interes(cfg, est, serie, para="avisar"):
    """Calles con interés: [(calle, nadador, motivo)] con motivo 'destacada', 'club' o 'filtro'."""
    f = est.get("filtros", {}).get(para, {})
    clubes, nadadores = set(f.get("clubes", [])), set(f.get("nadadores", []))
    dest = cfg.get("destacada", {}).get("nombre")
    club_dest = cfg.get("club_destacado")
    out = []
    for calle, x in serie["calles"].items():
        if x["nombre"] == dest:
            out.append((calle, x, "destacada"))
        elif x["club"] == club_dest:
            out.append((calle, x, "club"))
        elif x["club"] in clubes or x["nombre"] in nadadores:
            out.append((calle, x, "filtro"))
    return out


# ---------- longitud hablada ----------

_U = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce",
      "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve", "veinte", "veintiuno",
      "veintidós", "veintitrés", "veinticuatro", "veinticinco", "veintiséis", "veintisiete", "veintiocho", "veintinueve"]
_D = {3: "treinta", 4: "cuarenta", 5: "cincuenta", 6: "sesenta", 7: "setenta", 8: "ochenta", 9: "noventa"}
_C = {1: "ciento", 2: "doscientos", 3: "trescientos", 4: "cuatrocientos", 5: "quinientos", 6: "seiscientos",
      7: "setecientos", 8: "ochocientos", 9: "novecientos"}


def _numero(n):
    if n < 30:
        return _U[n]
    if n < 100:
        return _D[n // 10] + ("" if n % 10 == 0 else " y " + _U[n % 10])
    if n == 100:
        return "cien"
    if n < 1000:
        return _C[n // 100] + ("" if n % 100 == 0 else " " + _numero(n % 100))
    if n < 2000:
        return "mil" + ("" if n % 1000 == 0 else " " + _numero(n % 1000))
    return str(n)


def silabas(texto):
    """Sílabas habladas aproximadas (grupos de vocales), con los números leídos en voz alta.

    Siri pregunta antes de leer un aviso «largo» según lo que tarda en decirlo, no según
    los caracteres: el 2026-10-14 leyó directamente avisos de hasta 43 sílabas (124
    caracteres) y preguntó con 45 (114 caracteres) y 53.
    """
    t = re.sub(r"\d+", lambda m: " " + _numero(int(m.group())) + " ", texto.lower())
    return sum(max(1, len(re.findall(r"[aeiouáéíóúü]+", w))) for w in re.findall(r"[a-záéíóúüñ]+", t))


def _lista_calles(calles):
    """«calle 4» / «calles 4 y 6» / «calles 1, 4 y 6»."""
    cs = sorted(calles, key=int)
    if len(cs) == 1:
        return f"calle {cs[0]}"
    return "calles " + ", ".join(cs[:-1]) + f" y {cs[-1]}"


def texto_aviso(cfg, jor, plano, j, actual, cortos, est, previo=False, minutos=None):
    """Título y texto del aviso, sin pasar de `max_silabas_aviso` sílabas habladas (título + texto).

    Si no cabe, se acorta por este orden: «cuando» más corto, sin apellidos, solo
    calles, sin el total de pruebas y, como último recurso, solo cuántos hay de cada
    club. La prueba, la serie, el estilo y la destacada no se quitan nunca.
    """
    h = plano[j]
    estilo = h["prueba"]["nombre"].lower()
    limite = cfg.get("max_silabas_aviso", 40)
    total = max(p["n"] for p in jor["pruebas"])  # numeración oficial, aunque falte alguna prueba
    k = j - actual if actual >= 0 else j + 1
    calles = interes(cfg, est, h["serie"])
    dest = cfg.get("destacada", {})
    alias = dest.get("alias", "")
    calle_dest = next((c for c, x, m in calles if m == "destacada"), None)
    club_dest = club_corto(cfg, cfg.get("club_destacado", ""))
    por_club = {}
    for calle, x, motivo in calles:
        if motivo != "destacada":
            por_club.setdefault(club_corto(cfg, x["club"]), []).append((calle, cortos[x["nombre"]]))
    clubes = sorted(por_club, key=lambda c: (c != club_dest, c))

    def cuando(corto):
        if k <= 0:
            return "Ahora"
        if k == 1:
            return "En la siguiente" if corto else "En la siguiente serie"
        return f"En {k} series" if corto else f"Dentro de {k} series"

    def gente(nivel):
        """nivel 0: nombre y apellido; 1: solo nombre; 2: solo calles; 3: cuántos por club; 4: cuántos en total."""
        partes = [f"{alias}, calle {calle_dest}"] if calle_dest else []
        if nivel == 4:
            otros = sum(len(v) for v in por_club.values())
            return ". ".join(partes + ([f"{otros} más de tus filtros"] if otros else []))
        for club in clubes:
            filas = sorted(por_club[club], key=lambda x: int(x[0]))
            if nivel == 3:
                partes.append(f"{len(filas)} de {club}")
            elif nivel == 2:
                partes.append(f"{club}: {_lista_calles([c for c, _ in filas])}")
            else:
                nombres = [n if nivel == 0 else n.split(" ")[0] for _, n in filas]
                partes.append(f"{club}: " + "; ".join(f"calle {c}, {n}" for (c, _), n in zip(filas, nombres)))
        return ". ".join(partes)

    if previo:
        opciones = [
            (f"{alias} en {minutos} minutos",
             f"Prueba {h['p']} de {total}, serie {h['s']} de {h['ns']}, calle {calle_dest}. {estilo.capitalize()}."),
            (f"{alias} en {minutos} minutos",
             f"Prueba {h['p']}, serie {h['s']} de {h['ns']}, calle {calle_dest}. {estilo.capitalize()}."),
        ]
    else:
        opciones = []
        for corto_cuando, nivel, con_total in [(False, 0, True), (True, 0, True), (True, 1, True),
                                               (True, 2, True), (True, 2, False), (True, 3, False), (True, 4, False)]:
            titulo = f"Prueba {h['p']}" + (f" de {total}" if con_total else "") + f", serie {h['s']} de {h['ns']}"
            opciones.append((titulo, f"{cuando(corto_cuando)}. {estilo.capitalize()}. {gente(nivel)}."))
    for titulo, msg in opciones:
        if silabas(f"{titulo}. {msg}") <= limite:
            return titulo, msg
    return opciones[-1]   # ni así cabe: Siri preguntará, pero el aviso llega igual


def enviar(cfg, titulo, mensaje):
    cuerpo = json.dumps({"title": titulo, "message": mensaje, "url": cfg.get("url_guia", "")}).encode()
    req = urllib.request.Request(cfg["webhook"], data=cuerpo, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()


def anotar(est, texto):
    est.setdefault("historial", []).insert(0, {"t": ahora_ms(), "texto": texto})
    del est["historial"][80:]


def rearmar(cfg, est, plano, ini, t):
    """Tras mover el ancla, vuelven a avisar las series que han quedado lejos."""
    ant = 60000 * est.get("antelacion_min", cfg.get("antelacion_min", 3))
    ant_d = 60000 * cfg.get("antelacion_destacada_min", 8)
    av = est.setdefault("avisados", {})
    for j, h in enumerate(plano):
        marcas = av.get(h["id"])
        if not marcas:
            continue
        falta = ini[j] - t
        if falta > ant + 60000:
            marcas.pop("normal", None)
        if falta > ant_d + 60000:
            marcas.pop("previo", None)
        if not marcas:
            av.pop(h["id"])


def revisar():
    cfg, jor = cargar(CONFIG, None), cargar(JORNADA, None)
    if not cfg or not jor:
        return
    with lock:
        est = cargar(ESTADO, {})
        if not est.get("avisos_activos", True):
            return
        plano = series_planas(jor)
        ini = horario(plano, jor, est.get("ancla"))
        t = ahora_ms()
        actual = serie_actual(ini, t)
        cortos = nombres_cortos({x["nombre"] for h in plano for x in h["serie"]["calles"].values()})
        ant = 60000 * est.get("antelacion_min", cfg.get("antelacion_min", 3))
        ant_d = 60000 * cfg.get("antelacion_destacada_min", 8)
        av = est.setdefault("avisados", {})
        enviados = 0
        for j, h in enumerate(plano):
            falta = ini[j] - t
            if falta < -20000 or falta > ant_d or enviados >= 3:
                continue
            calles = interes(cfg, est, h["serie"])
            if not calles:
                continue
            marcas = av.setdefault(h["id"], {})
            hay_dest = any(m == "destacada" for _, _, m in calles)
            try:
                if hay_dest and "previo" not in marcas and "normal" not in marcas and falta > ant:
                    titulo, msg = texto_aviso(cfg, jor, plano, j, actual, cortos, est, previo=True,
                                              minutos=max(1, round(falta / 60000)))
                    enviar(cfg, titulo, msg)
                    marcas["previo"] = t
                    anotar(est, f"{titulo}. {msg}")
                    enviados += 1
                if "normal" not in marcas and falta <= ant:
                    titulo, msg = texto_aviso(cfg, jor, plano, j, actual, cortos, est)
                    enviar(cfg, titulo, msg)
                    marcas["normal"] = t
                    anotar(est, f"{titulo}. {msg}")
                    enviados += 1
            except Exception as e:
                anotar(est, f"No se pudo mandar el aviso de {h['id']}: {e}")
            if not marcas:
                av.pop(h["id"], None)
        guardar(ESTADO, est)


def bucle():
    while True:
        try:
            revisar()
        except Exception:
            traceback.print_exc()
        time.sleep(10)


# ---------- API ----------

def estado_publico():
    cfg, jor = cargar(CONFIG, {}) or {}, cargar(JORNADA, None)
    est = cargar(ESTADO, {})
    if not jor:
        return {"error": "Falta /data/jornada.json"}
    plano = series_planas(jor)
    ini = horario(plano, jor, est.get("ancla"))
    oficial = horario(plano, jor, None)
    cortos = nombres_cortos({x["nombre"] for h in plano for x in h["serie"]["calles"].values()})
    return {
        "jornada": jor["jornada"], "pruebas": jor["pruebas"], "ahora": ahora_ms(),
        "inicios": ini, "oficial": oficial, "ids": [h["id"] for h in plano],
        "ancla": est.get("ancla"), "filtros": est.get("filtros", {"ver": {}, "avisar": {}}),
        "avisos_activos": est.get("avisos_activos", True),
        "antelacion_min": est.get("antelacion_min", cfg.get("antelacion_min", 3)),
        "destacada": cfg.get("destacada", {}), "club_destacado": cfg.get("club_destacado"),
        "alias_clubes": cfg.get("alias_clubes", {}), "cortos": cortos,
        "avisados": est.get("avisados", {}), "historial": est.get("historial", [])[:30],
    }


class Web(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, datos, código=200):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode()
        self.send_response(código)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        ruta = self.path.split("?")[0]
        if ruta.endswith("/api/estado"):
            return self._json(estado_publico())
        with open(f"{WWW}/index.html", "rb") as f:
            cuerpo = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_POST(self):
        ruta = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        datos = json.loads(self.rfile.read(n) or b"{}")
        cfg, jor = cargar(CONFIG, {}) or {}, cargar(JORNADA, None)
        with lock:
            est = cargar(ESTADO, {})
            if ruta.endswith("/api/ancla"):
                plano = series_planas(jor)
                t = ahora_ms()
                if datos.get("oficial"):
                    est.pop("ancla", None)
                    anotar(est, "Marcador devuelto al horario oficial")
                else:
                    if "delta" in datos:
                        ini = horario(plano, jor, est.get("ancla"))
                        i = serie_actual(ini, t) + int(datos["delta"])
                    else:
                        i = int(datos["i"])
                    i = max(0, min(i, len(plano) - 1))
                    est["ancla"] = {"i": i, "t": t}
                    anotar(est, f"Marcador recolocado: ahora nada la prueba {plano[i]['p']}, serie {plano[i]['s']}")
                rearmar(cfg, est, series_planas(jor), horario(series_planas(jor), jor, est.get("ancla")), t)
            elif ruta.endswith("/api/filtros"):
                est["filtros"] = {k: {"clubes": list(v.get("clubes", [])), "nadadores": list(v.get("nadadores", [])),
                                      **({"solo_interes": bool(v.get("solo_interes"))} if k == "ver" else {})}
                                  for k, v in datos.items() if k in ("ver", "avisar")}
            elif ruta.endswith("/api/ajustes"):
                if "avisos_activos" in datos:
                    est["avisos_activos"] = bool(datos["avisos_activos"])
                    anotar(est, "Avisos activados" if est["avisos_activos"] else "Avisos silenciados")
                if "antelacion_min" in datos:
                    est["antelacion_min"] = max(1, min(15, int(datos["antelacion_min"])))
            elif ruta.endswith("/api/prueba"):
                try:
                    enviar(cfg, "Guía de jornada", "Aviso de prueba. Si me oyes, los avisos funcionan.")
                    anotar(est, "Aviso de prueba enviado")
                except Exception as e:
                    anotar(est, f"El aviso de prueba falló: {e}")
            else:
                return self._json({"error": "ruta desconocida"}, 404)
            guardar(ESTADO, est)
        threading.Thread(target=revisar, daemon=True).start()
        self._json(estado_publico())


if __name__ == "__main__":
    threading.Thread(target=bucle, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8080), Web).serve_forever()
