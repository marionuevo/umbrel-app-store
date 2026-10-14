# Vigía Fedecanat

Vigila una carpeta compartida del owncloud de la Federación Canaria de Natación y manda un aviso al iPhone, a través de Home Assistant, cuando aparece algo nuevo: listas de salida, horarios o resultados.

## Cómo funciona

- Cada `intervalo_min` minutos (15 por defecto) lista la carpeta con WebDAV (`PROPFIND`, `Depth: infinity`) en `http://fedecanat.es/owncloud/public.php/webdav`. El usuario es el token del enlace público y la contraseña va vacía. Una petición `GET` normal no sirve, porque el owncloud monta la lista de archivos con JavaScript.
- Compara el resultado con `data/estado.json`. Avisa de los archivos nuevos y de los que han cambiado (etag distinto). También avisa de las carpetas nuevas que llegan vacías, como la de una jornada que aún no tiene archivos.
- El aviso es un `POST` con `{title, message, url}` al webhook de Home Assistant. La automatización `automation.fedecanat_aviso_de_archivos_nuevos` lo reenvía a `notify.mobile_app_marios_iphone_14_pro`; al tocar el aviso se abre la carpeta.
- Si el aviso falla, el cambio no se da por visto y se reintenta en la siguiente comprobación.
- Si la carpeta no se puede leer durante más de 3 horas seguidas, avisa una vez, y vuelve a avisar cuando se recupera.
- La primera lectura no avisa de lo que ya hay. Solo manda un aviso de inicio, que sirve para comprobar la cadena completa.
- Página de estado en el puerto 9096, detrás del login de Umbrel. Muestra la última comprobación, el contenido de la carpeta y el historial, con botones para «Comprobar ahora» y «Enviar aviso de prueba».

## Configuración

`data/config.json` dentro de la app (`~/umbrel/app-data/marionuevo-fedecanat-vigia/data/config.json`). No está en git porque lleva el webhook de Home Assistant, y quien conoce su id puede mandarte avisos desde la red de casa. Se parte de `config.example.json`:

| Clave | Qué es |
|---|---|
| `servidor` | `http://fedecanat.es` |
| `share_token` | El `s/<token>` del enlace público de la federación |
| `carpeta` | Ruta dentro del enlace, con `/` al principio y al final, por ejemplo `/2-TENERIFE/` |
| `intervalo_min` | Minutos entre comprobaciones |
| `enlace` | Enlace que abre el aviso de inicio |
| `webhook` | `http://10.80.20.22:8123/api/webhook/<id>`. La automatización tiene `local_only`, así que solo responde desde la red local |

Los cambios en la configuración se aplican en la siguiente comprobación, o al pulsar «Comprobar ahora». Si se cambia `carpeta`, hay que mandar `data/estado.json` a la papelera para que la primera lectura no avise de todo lo que ya había.

## Imagen

`python:3.13.7-alpine3.22`, fijada por digest. El script solo usa la biblioteca estándar y va montado de solo lectura desde la carpeta de la app. Se ejecuta como `1000:1000` (el usuario `umbrel`) para poder escribir en `data/` sin sudo.
