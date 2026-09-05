"""Sigue el log de nginx y va metiendo lo nuevo en la base.

Es un `tail -f` con memoria: guarda (inodo, offset) en la base, así que un
reinicio del contenedor no reprocesa lo ya leído ni se salta lo que llegó
mientras estaba parado.
"""

import os
import threading
import time

from . import analizar, config, datos

# Cuánto se acumula antes de escribir. Al arrancar con un log grande esto hace
# la diferencia entre una inserción por línea y una por cada 2.000.
LOTE = 2000
INTERVALO_LOTE = 2.0


class Seguidor(threading.Thread):
    daemon = True

    def __init__(self, avisar=None):
        super().__init__(name="seguidor")
        self.ruta = config.LOG_PATH
        self.avisar = avisar          # se llama tras cada lote guardado
        self.parar = threading.Event()
        self.leidas = 0
        self.descartadas = 0
        self.ultimo_error = ""
        self._f = None
        self._inodo = None
        self._resto = ""

    # ── apertura y posición ──────────────────────────────────────────────────
    def _abrir(self):
        """Abre el log y decide desde qué byte seguir."""
        try:
            f = open(self.ruta, "r", encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return False
        st = os.fstat(f.fileno())

        inodo_guardado = datos.leer_estado("inodo")
        offset_guardado = int(datos.leer_estado("offset", "0") or 0)

        if inodo_guardado == str(st.st_ino) and offset_guardado <= st.st_size:
            # Mismo fichero que la última vez: se retoma donde se dejó.
            f.seek(offset_guardado)
        else:
            # Fichero nuevo (rotado o primera vez): se lee entero. Si es el
            # mismo inodo pero ha encogido, lo truncaron y también toca de cero.
            f.seek(0)

        if self._f:
            self._f.close()
        self._f, self._inodo, self._resto = f, st.st_ino, ""
        datos.escribir_estado("inodo", st.st_ino)
        datos.escribir_estado("offset", f.tell())
        return True

    def _rotado(self):
        """¿El nombre apunta ya a otro fichero del que tenemos abierto?"""
        try:
            return os.stat(self.ruta).st_ino != self._inodo
        except FileNotFoundError:
            return False

    # ── lectura ──────────────────────────────────────────────────────────────
    def _consumir(self):
        """Lee lo disponible y devuelve las filas listas para guardar."""
        trozo = self._f.read()
        if not trozo:
            return []
        # La última línea puede venir a medias: nginx escribe con una sola
        # write() por petición, pero leer justo en mitad de ella es posible.
        datos_texto = self._resto + trozo
        lineas = datos_texto.split("\n")
        self._resto = lineas.pop()

        filas = []
        for linea in lineas:
            fila = analizar.analizar(linea)
            if fila:
                filas.append(fila)
            elif linea.strip():
                self.descartadas += 1
        return filas

    def _quizas_truncar(self):
        """Recorta el log cuando se pasa de tamaño y ya está todo ingerido.

        nginx lo tiene abierto en O_APPEND, así que tras truncarlo su siguiente
        escritura cae sola en el offset 0 y no hace falta mandarle un USR1
        (que desde aquí, sin el socket de Docker, no se podría).

        Se pierde lo que nginx escriba entre el read() de arriba y el truncate:
        una ventana de microsegundos que a este volumen es despreciable, y el
        precio de no tener que meter logrotate en el contenedor de nginx.
        """
        if config.MAX_LOG_BYTES <= 0:
            return
        try:
            if os.fstat(self._f.fileno()).st_size < config.MAX_LOG_BYTES:
                return
            os.truncate(self.ruta, 0)
            self._f.seek(0)
            self._resto = ""
            datos.escribir_estado("offset", 0)
        except OSError as e:
            self.ultimo_error = f"no se pudo truncar el log: {e}"

    # ── bucle ────────────────────────────────────────────────────────────────
    def run(self):
        pendientes = []
        ultimo_guardado = time.time()
        ultima_purga = 0.0

        while not self.parar.is_set():
            try:
                if self._f is None and not self._abrir():
                    # Aún no existe: nginx no ha servido nada todavía.
                    self.parar.wait(2.0)
                    continue

                pendientes.extend(self._consumir())

                hay_lote = len(pendientes) >= LOTE
                toca_por_tiempo = pendientes and (time.time() - ultimo_guardado) >= INTERVALO_LOTE
                if hay_lote or toca_por_tiempo:
                    datos.guardar(pendientes)
                    self.leidas += len(pendientes)
                    pendientes = []
                    datos.escribir_estado("offset", self._f.tell())
                    ultimo_guardado = time.time()
                    if self.avisar:
                        self.avisar()

                if self._rotado():
                    # Vaciar la cola del fichero viejo antes de soltarlo.
                    resto = self._consumir()
                    if resto:
                        datos.guardar(resto)
                        self.leidas += len(resto)
                    self._abrir()
                    continue

                self._quizas_truncar()

                ahora = time.time()
                if ahora - ultima_purga > 3600:
                    datos.purgar()
                    ultima_purga = ahora

                if not hay_lote:
                    self.parar.wait(config.POLL_SECONDS)

            except Exception as e:                      # noqa: BLE001
                # Nunca morir: el panel sin datos nuevos sigue siendo útil, y
                # un error transitorio (disco lleno, base bloqueada) se pasa.
                self.ultimo_error = f"{type(e).__name__}: {e}"
                self.parar.wait(2.0)

    def estado(self):
        try:
            tam = os.path.getsize(self.ruta)
        except OSError:
            tam = 0
        return {
            "log": self.ruta,
            "existe": os.path.exists(self.ruta),
            "tam_log": tam,
            "leidas": self.leidas,
            "descartadas": self.descartadas,
            "error": self.ultimo_error,
        }
