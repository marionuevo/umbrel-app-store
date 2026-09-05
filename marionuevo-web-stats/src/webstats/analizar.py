"""De una línea del log de nginx a una fila de la base de datos."""

import json
from datetime import datetime

from . import clasificar

CAMPOS = (
    "ts", "ip", "cc", "host", "metodo", "ruta", "consulta", "estado", "bytes",
    "referer", "ua", "rt", "tipo", "pagina", "navegador", "version_nav",
    "sistema", "dispositivo", "proc_tipo", "proc_dominio",
)


def _instante(valor):
    """$time_iso8601 llega como 2026-09-05T20:17:52+00:00."""
    try:
        return int(datetime.fromisoformat(valor).timestamp())
    except (ValueError, TypeError):
        return 0


def analizar(linea):
    """Devuelve un dict con CAMPOS, o None si la línea no sirve.

    Una línea rota no debe tumbar el seguidor: nginx puede escribir a medias si
    el disco se llena, y el truncado deja restos. Se descarta y se sigue.
    """
    linea = linea.strip()
    if not linea or not linea.startswith("{"):
        return None
    try:
        d = json.loads(linea)
    except (json.JSONDecodeError, ValueError):
        return None

    ts = _instante(d.get("t"))
    if not ts:
        return None

    uri = d.get("uri") or "/"
    ruta, _, consulta = uri.partition("?")
    ruta = ruta or "/"

    ua = d.get("ua") or ""
    host = (d.get("host") or "").lower()
    referer = d.get("ref") or ""

    tipo = clasificar.tipo_de_visita(ua, uri)
    nav, ver = clasificar.navegador(ua)
    proc_tipo, proc_dom = clasificar.procedencia(referer, host)

    # El país lo pone Cloudflare. "XX" es su forma de decir que no lo sabe, y
    # "T1" es Tor; ninguno de los dos es un país, así que se dejan vacíos.
    cc = (d.get("cc") or "").upper()
    if cc in ("XX", "T1", "-"):
        cc = ""

    try:
        rt = float(d.get("rt") or 0)
    except (TypeError, ValueError):
        rt = 0.0

    return {
        "ts": ts,
        "ip": d.get("ip") or "",
        "cc": cc,
        "host": host,
        "metodo": d.get("metodo") or d.get("method") or "",
        "ruta": ruta[:512],
        "consulta": consulta[:512],
        "estado": int(d.get("status") or 0),
        "bytes": int(d.get("bytes") or 0),
        "referer": referer[:512],
        "ua": ua[:512],
        "rt": rt,
        "tipo": tipo,
        "pagina": 1 if (tipo == "persona" and clasificar.es_pagina(ruta)) else 0,
        "navegador": nav,
        "version_nav": ver,
        "sistema": clasificar.sistema(ua),
        "dispositivo": clasificar.dispositivo(ua),
        "proc_tipo": proc_tipo,
        "proc_dominio": proc_dom[:255],
    }
