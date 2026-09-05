"""Arranque: prepara la base, lanza el seguidor y sirve el panel."""

import os
import signal
import sys

from . import clasificar, config, datos, seguidor, servidor


def main():
    os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)

    datos.preparar()
    # A los dominios declarados en el compose se suman los que ya se han
    # servido de hecho: si mañana se añade una web y nadie toca la variable,
    # su tráfico interno se sigue reconociendo como tal.
    clasificar.registrar_hosts_propios(config.OWN_HOSTS + datos.sitios_conocidos())

    hilo = seguidor.Seguidor()
    servidor.SEGUIDOR = hilo
    hilo.start()

    def adios(*_):
        hilo.parar.set()
        sys.exit(0)

    signal.signal(signal.SIGTERM, adios)
    signal.signal(signal.SIGINT, adios)

    print(
        f"webstats escuchando en {config.BIND_HOST}:{config.BIND_PORT} · "
        f"log={config.LOG_PATH} · base={config.DB_PATH}",
        flush=True,
    )
    servidor.servir()


if __name__ == "__main__":
    main()
