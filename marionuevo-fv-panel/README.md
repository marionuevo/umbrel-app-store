# Fotovoltaica

Panel en directo de la fotovoltaica de casa. Es un HTML (`www/index.html`) que
se conecta al websocket de Home Assistant, servido por nginx detrás del login
de Umbrel en el puerto 9090.

## Token de Home Assistant

El panel lee `config.local.js`, que nginx sirve desde `data/` de la app. No está
en git: se crea a mano en el Umbrel después de instalar la app.

```js
window.HA_CONFIG = { token: "<token de larga duración>" };
```

Ruta en el Umbrel: `~/umbrel/app-data/marionuevo-fv-panel/data/config.local.js`.
Sin `url`, el panel usa el mismo equipo en el puerto 8123. Usa un token propio
para el panel (Perfil de Home Assistant → Tokens de acceso de larga duración),
para poder revocarlo sin tocar nada más.

Si el fichero no existe, el panel pide la dirección y el token la primera vez y
los guarda en ese navegador.

## Desarrollo

`~/AIWork/solar-panel/index.html` en el Mac es un enlace a `www/index.html`;
allí `config.local.js` lleva el token del Mac.
