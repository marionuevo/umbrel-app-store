# Solar Live (Fotovoltaica)

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

## Precios del contrato

Opcionales, en el mismo `config.local.js` y sin impuestos:

```js
window.HA_CONFIG.tariff = { import: { p1: 0.20, p2: 0.12, p3: 0.10 }, export: 0.04 };
```

`import` admite los tres periodos del peaje 2.0TD (el panel elige el de cada hora
local, con fines de semana y festivos nacionales de fecha fija en P3) o un precio
único. También admite una lista con la fecha en que entra cada tarifa, para que
una renovación cambie sola:

```js
window.HA_CONFIG.tariff = [
  { import: { p1: 0.20, p2: 0.12, p3: 0.10 }, export: 0.04 },
  { from: "2027-01-01", import: { p1: 0.22, p2: 0.15, p3: 0.12 }, export: 0.035 },
];
```

Sin `tariff` se usan los sensores de tarifa de SolarNet.

## Vista 3D

`www/3d.html` es la misma conexión dibujada en three.js: casa con tejado a dos
aguas (cumbrera norte-sur, faldones a 20°), las 5 × 2 placas en vertical en el
faldón oeste, el sol en su posición real (latitud y longitud de `get_config` de
Home Assistant) con el arco del día y sus sombras, y una torre de la red. El
flujo corre por los cables: placas → inversor → contador y contador ↔ torre
(salvia al verter, coral al comprar). three.js r170 va dentro de la app, en
`www/vendor/three/` (licencia MIT), para no depender de un CDN. Dibuja como
mucho a 30 fps; con «reducir movimiento» solo dibuja cuando cambia algo.

## Desarrollo

`~/AIWork/solar-panel/index.html` en el Mac es un enlace a `www/index.html`;
allí `config.local.js` lleva el token del Mac. `3d.html` y `vendor/` también son
enlaces. Con la vista 3D hace falta un servidor (los módulos no cargan desde
`file://`): `python3 -m http.server 8765` en esa carpeta.
