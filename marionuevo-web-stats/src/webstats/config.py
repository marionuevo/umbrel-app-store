"""Ajustes, todos por variable de entorno para que el compose los fije."""

import os


def _int(nombre, por_defecto):
    try:
        return int(os.environ.get(nombre) or por_defecto)
    except ValueError:
        return por_defecto


def _float(nombre, por_defecto):
    try:
        return float(os.environ.get(nombre) or por_defecto)
    except ValueError:
        return por_defecto


def _lista(nombre):
    return [x.strip().lower() for x in (os.environ.get(nombre) or "").split(",") if x.strip()]


LOG_PATH = os.environ.get("WEBSTATS_LOG") or "/logs/stats.log"
DB_PATH = os.environ.get("WEBSTATS_DB") or "/data/webstats.db"

BIND_HOST = os.environ.get("WEBSTATS_BIND") or "0.0.0.0"
BIND_PORT = _int("WEBSTATS_PORT", 8080)

# Cada cuánto se mira si el log ha crecido. El coste es un fstat por vuelta.
POLL_SECONDS = _float("WEBSTATS_POLL", 0.5)

# Los datos crudos se guardan enteros durante este tiempo. A ~4.000 peticiones
# al día, medio año son ~700.000 filas: SQLite las agrega al vuelo sin
# despeinarse, así que no hacen falta tablas de resumen.
RETENTION_DAYS = _int("WEBSTATS_RETENTION_DAYS", 180)

# nginx:alpine NO trae logrotate y el contenedor no puede recibir un USR1 desde
# aquí, así que stats.log crecería sin fin. Cuando pasa de este tamaño y todo
# está ya ingerido, se trunca en sitio: nginx lo abrió con O_APPEND, así que su
# siguiente escritura vuelve sola al offset 0 sin reabrir nada.
MAX_LOG_BYTES = _int("WEBSTATS_MAX_LOG_MB", 256) * 1024 * 1024

# Dominios propios: un referer de estos es navegación interna, no procedencia.
OWN_HOSTS = _lista("WEBSTATS_HOSTS")

# Ventana para "ahora mismo": visitantes distintos vistos en los últimos N min.
LIVE_WINDOW_MIN = _int("WEBSTATS_LIVE_WINDOW_MIN", 5)
