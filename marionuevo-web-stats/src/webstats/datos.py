"""SQLite: esquema, escritura por lotes y las consultas del panel.

Se guardan las filas crudas y se agrega al vuelo. Con el tráfico de estas cinco
webs (~4.000 peticiones/día) una consulta sobre 30 días toca ~120.000 filas y
tarda milisegundos, así que las tablas de resumen solo añadirían sitios donde
equivocarse.
"""

import sqlite3
import threading
import time

from . import config

_local = threading.local()
_escritura = threading.Lock()

ESQUEMA = """
CREATE TABLE IF NOT EXISTS peticiones (
    id           INTEGER PRIMARY KEY,
    ts           INTEGER NOT NULL,
    ip           TEXT    NOT NULL DEFAULT '',
    cc           TEXT    NOT NULL DEFAULT '',
    host         TEXT    NOT NULL DEFAULT '',
    metodo       TEXT    NOT NULL DEFAULT '',
    ruta         TEXT    NOT NULL DEFAULT '',
    consulta     TEXT    NOT NULL DEFAULT '',
    estado       INTEGER NOT NULL DEFAULT 0,
    bytes        INTEGER NOT NULL DEFAULT 0,
    referer      TEXT    NOT NULL DEFAULT '',
    ua           TEXT    NOT NULL DEFAULT '',
    rt           REAL    NOT NULL DEFAULT 0,
    tipo         TEXT    NOT NULL DEFAULT 'persona',
    pagina       INTEGER NOT NULL DEFAULT 0,
    navegador    TEXT    NOT NULL DEFAULT '',
    version_nav  TEXT    NOT NULL DEFAULT '',
    sistema      TEXT    NOT NULL DEFAULT '',
    dispositivo  TEXT    NOT NULL DEFAULT '',
    proc_tipo    TEXT    NOT NULL DEFAULT '',
    proc_dominio TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS i_pet_ts        ON peticiones(ts);
CREATE INDEX IF NOT EXISTS i_pet_host_ts   ON peticiones(host, ts);
CREATE INDEX IF NOT EXISTS i_pet_tipo_ts   ON peticiones(tipo, ts);

CREATE TABLE IF NOT EXISTS estado_lector (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
"""

COLUMNAS = (
    "ts", "ip", "cc", "host", "metodo", "ruta", "consulta", "estado", "bytes",
    "referer", "ua", "rt", "tipo", "pagina", "navegador", "version_nav",
    "sistema", "dispositivo", "proc_tipo", "proc_dominio",
)

_INSERT = "INSERT INTO peticiones ({}) VALUES ({})".format(
    ",".join(COLUMNAS), ",".join("?" * len(COLUMNAS))
)


def conexion():
    """Una conexión por hilo. sqlite3 no las deja compartir."""
    c = getattr(_local, "con", None)
    if c is None:
        c = sqlite3.connect(config.DB_PATH, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")     # lectores y escritor a la vez
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA busy_timeout=30000")
        _local.con = c
    return c


def preparar():
    c = conexion()
    with _escritura:
        c.executescript(ESQUEMA)


def guardar(filas):
    """Inserta un lote. Devuelve cuántas entraron."""
    if not filas:
        return 0
    datos = [tuple(f[k] for k in COLUMNAS) for f in filas]
    c = conexion()
    with _escritura:
        c.execute("BEGIN")
        try:
            c.executemany(_INSERT, datos)
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
    return len(datos)


def leer_estado(clave, por_defecto=None):
    fila = conexion().execute(
        "SELECT valor FROM estado_lector WHERE clave=?", (clave,)
    ).fetchone()
    return fila["valor"] if fila else por_defecto


def escribir_estado(clave, valor):
    c = conexion()
    with _escritura:
        c.execute(
            "INSERT INTO estado_lector(clave,valor) VALUES(?,?) "
            "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
            (clave, str(valor)),
        )


def purgar():
    """Borra lo que se ha pasado de la retención. Devuelve filas eliminadas."""
    if config.RETENTION_DAYS <= 0:
        return 0
    corte = int(time.time()) - config.RETENTION_DAYS * 86400
    c = conexion()
    with _escritura:
        cur = c.execute("DELETE FROM peticiones WHERE ts < ?", (corte,))
    return cur.rowcount


# ── Consultas ────────────────────────────────────────────────────────────────

RANGOS = {
    "1h":   (3600,          60),
    "6h":   (6 * 3600,     300),
    "24h":  (86400,       1800),
    "7d":   (7 * 86400,  10800),
    "30d":  (30 * 86400, 86400),
    "todo": (None,       86400),
}


def ventana(rango):
    """(desde, hasta, segundos_por_cubo) en epoch."""
    ahora = int(time.time())
    largo, cubo = RANGOS.get(rango, RANGOS["24h"])
    if largo is None:
        fila = conexion().execute("SELECT MIN(ts) AS m FROM peticiones").fetchone()
        desde = fila["m"] if fila and fila["m"] else ahora - 86400
        # Con muchos meses de historia, un cubo de un día da una serie legible.
        dias = max(1, (ahora - desde) // 86400)
        cubo = 3600 if dias <= 2 else 86400
    else:
        desde = ahora - largo
    return desde, ahora, cubo


def _filtro(host, tipo, desde, hasta):
    sql = ["ts >= ?", "ts <= ?"]
    par = [desde, hasta]
    if host and host != "todos":
        sql.append("host = ?")
        par.append(host.lower())
    if tipo and tipo != "todos":
        sql.append("tipo = ?")
        par.append(tipo)
    return " AND ".join(sql), par


def resumen(host, tipo, desde, hasta):
    c = conexion()
    donde, par = _filtro(host, tipo, desde, hasta)
    fila = c.execute(
        f"""SELECT COUNT(*)                AS peticiones,
                   COALESCE(SUM(pagina),0) AS paginas,
                   COUNT(DISTINCT ip)      AS visitantes,
                   COALESCE(SUM(bytes),0)  AS bytes,
                   COALESCE(AVG(rt),0)     AS rt
              FROM peticiones WHERE {donde}""",
        par,
    ).fetchone()

    # El reparto por tipo ignora el filtro de tipo a propósito: es lo que deja
    # ver de un vistazo cuánto del tráfico es basura sin cambiar de filtro.
    donde_sin, par_sin = _filtro(host, "todos", desde, hasta)
    reparto = {
        r["tipo"]: {"peticiones": r["n"], "bytes": r["b"]}
        for r in c.execute(
            f"SELECT tipo, COUNT(*) n, COALESCE(SUM(bytes),0) b "
            f"FROM peticiones WHERE {donde_sin} GROUP BY tipo",
            par_sin,
        )
    }

    ahora = int(time.time())
    activos = c.execute(
        f"SELECT COUNT(DISTINCT ip) n FROM peticiones "
        f"WHERE ts >= ? AND tipo='persona'"
        + (" AND host=?" if host and host != "todos" else ""),
        [ahora - config.LIVE_WINDOW_MIN * 60] + ([host.lower()] if host and host != "todos" else []),
    ).fetchone()["n"]

    return {
        "peticiones": fila["peticiones"],
        "paginas": fila["paginas"],
        "visitantes": fila["visitantes"],
        "bytes": fila["bytes"],
        "rt": round(fila["rt"], 4),
        "reparto": reparto,
        "activos": activos,
    }


def serie(host, tipo, desde, hasta, cubo):
    """Serie temporal por cubo y tipo de tráfico."""
    c = conexion()
    # El filtro de tipo NO se aplica: la serie apilada necesita los tres para
    # contar la historia completa. El panel decide qué capas pinta.
    donde, par = _filtro(host, "todos", desde, hasta)
    filas = c.execute(
        f"""SELECT (ts / ?) * ?            AS cubo,
                   tipo                    AS tipo,
                   COUNT(*)                AS peticiones,
                   COALESCE(SUM(pagina),0) AS paginas,
                   COALESCE(SUM(bytes),0)  AS bytes,
                   COUNT(DISTINCT ip)      AS visitantes
              FROM peticiones WHERE {donde}
             GROUP BY cubo, tipo ORDER BY cubo""",
        [cubo, cubo] + par,
    ).fetchall()

    # Rejilla completa: sin los huecos a cero la línea miente uniendo dos
    # puntos separados por horas de silencio.
    inicio = (desde // cubo) * cubo
    puntos = {}
    t = inicio
    while t <= hasta:
        puntos[t] = {
            "t": t,
            "persona": 0, "bot": 0, "sondeo": 0,
            # Los bytes van desglosados por tipo: si no, el gráfico de tráfico
            # no puede respetar el filtro y enseña bots con "Personas" puesto.
            "b_persona": 0, "b_bot": 0, "b_sondeo": 0,
            "paginas": 0, "bytes": 0, "visitantes": 0,
        }
        t += cubo
    for f in filas:
        p = puntos.get(f["cubo"])
        if p is None:
            continue
        p[f["tipo"]] = f["peticiones"]
        p["b_" + f["tipo"]] = f["bytes"]
        p["paginas"] += f["paginas"]
        p["bytes"] += f["bytes"]
        if f["tipo"] == "persona":
            p["visitantes"] = f["visitantes"]
    return list(puntos.values())


def _top(campo, host, tipo, desde, hasta, limite=12, extra=""):
    donde, par = _filtro(host, tipo, desde, hasta)
    if extra:
        donde += " AND " + extra
    return [
        dict(r)
        for r in conexion().execute(
            f"""SELECT {campo} AS clave, COUNT(*) AS n,
                       COALESCE(SUM(bytes),0) AS bytes,
                       COUNT(DISTINCT ip) AS visitantes
                  FROM peticiones
                 WHERE {donde} AND {campo} <> ''
                 GROUP BY {campo} ORDER BY n DESC LIMIT ?""",
            par + [limite],
        )
    ]


def listas(host, tipo, desde, hasta):
    """Todas las tablas del panel de una tacada."""
    donde, par = _filtro(host, tipo, desde, hasta)
    c = conexion()

    paginas = [
        dict(r)
        for r in c.execute(
            f"""SELECT ruta AS clave, COUNT(*) AS n,
                       COUNT(DISTINCT ip) AS visitantes,
                       COALESCE(SUM(bytes),0) AS bytes
                  FROM peticiones WHERE {donde} AND pagina = 1
                 GROUP BY ruta ORDER BY n DESC LIMIT 15""",
            par,
        )
    ]

    estados = [
        dict(r)
        for r in c.execute(
            f"""SELECT estado AS clave, COUNT(*) AS n
                  FROM peticiones WHERE {donde}
                 GROUP BY estado ORDER BY n DESC LIMIT 12""",
            par,
        )
    ]

    # Los sondeos se miran siempre enteros, pase lo que pase en el filtro de
    # tipo: es la vista de seguridad, y filtrarla por "personas" la vaciaría.
    donde_s, par_s = _filtro(host, "sondeo", desde, hasta)
    sondeos = [
        dict(r)
        for r in c.execute(
            f"""SELECT ruta AS clave, COUNT(*) AS n, COUNT(DISTINCT ip) AS visitantes
                  FROM peticiones WHERE {donde_s}
                 GROUP BY ruta ORDER BY n DESC LIMIT 12""",
            par_s,
        )
    ]

    return {
        "paginas": paginas,
        "sitios": _top("host", host, tipo, desde, hasta, 10),
        "paises": _top("cc", host, tipo, desde, hasta, 12),
        # Navegar de una página propia a otra no es "venir de" ningún sitio.
        # Además de lo ya marcado como interno se descarta cualquier dominio que
        # aparezca como host servido: así la lista se corrige sola cuando se
        # añade una web, sin depender de que WEBSTATS_HOSTS esté al día, y
        # arregla también lo ya guardado con la lista antigua.
        "procedencias": _top(
            "proc_dominio", host, tipo, desde, hasta, 12,
            extra="proc_tipo <> 'interno' AND proc_dominio NOT IN "
                  "(SELECT host FROM peticiones WHERE host <> '')",
        ),
        "proc_tipos": _top("proc_tipo", host, tipo, desde, hasta, 8),
        "navegadores": _top("navegador", host, tipo, desde, hasta, 8),
        "sistemas": _top("sistema", host, tipo, desde, hasta, 8),
        "dispositivos": _top("dispositivo", host, tipo, desde, hasta, 5),
        "estados": estados,
        "sondeos": sondeos,
        "agentes": _top("ua", host, "bot", desde, hasta, 10),
    }


def recientes(desde_id=0, limite=40, host="todos", tipo="todos"):
    """Últimas peticiones, para el hilo en vivo."""
    sql = ["id > ?"]
    par = [desde_id]
    if host and host != "todos":
        sql.append("host = ?")
        par.append(host.lower())
    if tipo and tipo != "todos":
        sql.append("tipo = ?")
        par.append(tipo)
    filas = conexion().execute(
        f"""SELECT id, ts, ip, cc, host, metodo, ruta, estado, bytes, tipo,
                   navegador, sistema, dispositivo, rt
              FROM peticiones WHERE {' AND '.join(sql)}
             ORDER BY id DESC LIMIT ?""",
        par + [limite],
    ).fetchall()
    return [dict(f) for f in reversed(filas)]


def ultimo_id():
    f = conexion().execute("SELECT COALESCE(MAX(id),0) AS m FROM peticiones").fetchone()
    return f["m"]


def sitios_conocidos():
    return [
        r["host"]
        for r in conexion().execute(
            "SELECT host, COUNT(*) n FROM peticiones WHERE host <> '' "
            "GROUP BY host ORDER BY n DESC"
        )
    ]
