"""API y panel. Solo biblioteca estándar: sin dependencias que instalar, el
contenedor arranca en frío y funciona sin red."""

import json
import mimetypes
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import config, datos

ESTATICOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

SEGUIDOR = None   # lo fija __main__ para que /api/salud lo pueda mirar


def _json(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class Manejador(BaseHTTPRequestHandler):
    server_version = "webstats"
    protocol_version = "HTTP/1.1"

    # El log por defecto escribe una línea por petición a stderr; el panel se
    # refresca solo y llenaría los logs de Docker de ruido.
    def log_message(self, *a):
        pass

    # ── utilidades de respuesta ──────────────────────────────────────────────
    def _responder(self, cuerpo, tipo="application/json; charset=utf-8", codigo=200):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(cuerpo)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _error(self, codigo, mensaje):
        self._responder(_json({"error": mensaje}), codigo=codigo)

    # ── rutas ────────────────────────────────────────────────────────────────
    def do_GET(self):
        partes = urlsplit(self.path)
        ruta = partes.path
        q = parse_qs(partes.query)

        try:
            if ruta == "/" or ruta == "/index.html":
                return self._estatico("index.html")
            if ruta in ("/estilo.css", "/panel.js"):
                return self._estatico(ruta.lstrip("/"))
            if ruta == "/api/panel":
                return self._panel(q)
            if ruta == "/api/vivo":
                return self._vivo(q)
            if ruta == "/api/salud":
                return self._salud()
            return self._error(404, "no existe")
        except BrokenPipeError:
            pass
        except Exception as e:                          # noqa: BLE001
            self._error(500, f"{type(e).__name__}: {e}")

    def _estatico(self, nombre):
        # nombre sale de una lista cerrada de arriba, pero se normaliza igual
        # por si mañana alguien añade una ruta con parámetro.
        destino = os.path.normpath(os.path.join(ESTATICOS, nombre))
        if not destino.startswith(ESTATICOS + os.sep):
            return self._error(403, "prohibido")
        try:
            with open(destino, "rb") as f:
                cuerpo = f.read()
        except FileNotFoundError:
            return self._error(404, "no existe")
        tipo = mimetypes.guess_type(destino)[0] or "application/octet-stream"
        self._responder(cuerpo, tipo=f"{tipo}; charset=utf-8")

    def _panel(self, q):
        rango = (q.get("rango") or ["24h"])[0]
        sitio = (q.get("sitio") or ["todos"])[0]
        tipo = (q.get("tipo") or ["persona"])[0]
        if rango not in datos.RANGOS:
            rango = "24h"
        if tipo not in ("todos", "persona", "bot", "sondeo"):
            tipo = "persona"

        desde, hasta, cubo = datos.ventana(rango)
        self._responder(_json({
            "rango": rango, "sitio": sitio, "tipo": tipo,
            "desde": desde, "hasta": hasta, "cubo": cubo,
            "resumen": datos.resumen(sitio, tipo, desde, hasta),
            "serie": datos.serie(sitio, tipo, desde, hasta, cubo),
            "listas": datos.listas(sitio, tipo, desde, hasta),
            "sitios": datos.sitios_conocidos(),
            "ventana_activos": config.LIVE_WINDOW_MIN,
        }))

    def _vivo(self, q):
        """SSE: empuja las peticiones nuevas conforme entran."""
        sitio = (q.get("sitio") or ["todos"])[0]
        tipo = (q.get("tipo") or ["todos"])[0]
        try:
            ultimo = int((q.get("desde") or ["0"])[0])
        except ValueError:
            ultimo = 0
        if ultimo <= 0:
            ultimo = max(0, datos.ultimo_id() - 30)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        latido = time.time()
        try:
            while True:
                filas = datos.recientes(ultimo, 60, sitio, tipo)
                if filas:
                    ultimo = max(f["id"] for f in filas)
                    self.wfile.write(b"event: peticiones\ndata: ")
                    self.wfile.write(_json(filas))
                    self.wfile.write(b"\n\n")
                    self.wfile.flush()
                    latido = time.time()
                elif time.time() - latido > 20:
                    # Un comentario mantiene viva la conexión a través de
                    # cualquier proxy que corte por inactividad.
                    self.wfile.write(b": latido\n\n")
                    self.wfile.flush()
                    latido = time.time()
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass    # el navegador cerró la pestaña; nada que hacer

    def _salud(self):
        s = SEGUIDOR.estado() if SEGUIDOR else {}
        s["filas"] = datos.ultimo_id()
        s["retencion_dias"] = config.RETENTION_DAYS
        self._responder(_json(s))


def servir():
    srv = ThreadingHTTPServer((config.BIND_HOST, config.BIND_PORT), Manejador)
    srv.daemon_threads = True
    srv.serve_forever()
