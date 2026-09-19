# Preparación de migración a umbrelOS 2.0

Esta rama prepara los paquetes; no es una autorización para cambiar el Umbrel
en producción. No hay un dispositivo beta/staging disponible, así que no se
debe instalar esta rama ni mover datos antes de verificar la versión estable.

## Qué cambia

- Nginx Md deja de fijar rutas `/home/umbrel/...`: en umbrelOS 2.0 se eligen
  tres carpetas desde Ajustes (configuración, sitios y logs).
- Estadísticas Web conserva su base SQLite en `${APP_DATA_DIR}/data`, declara
  ese directorio como `storage.dataRoot`, y selecciona los logs compartidos por
  `folderAccess` en vez de montar el `app-data` de Nginx Md.
- Los ajustes de Estadísticas Web se declaran para su edición desde la UI.
- WSTunnel no tiene datos que migrar; solo adopta la política de reinicio y la
  lectura del secreto ya no depende de un nombre de contenedor fijado.

## Cutover después de la versión estable

1. Revisa la versión exacta de umbrelOS 2.0 y conserva copias de los manifiestos
   y compose actuales.
2. Haz una copia verificable de `sites/`, `config/nginx/conf.d/`, el directorio
   de logs y `webstats.db`; mantén la configuración anterior para volver atrás.
3. Instala/actualiza Nginx Md y selecciona las carpetas de configuración y
   sitios existentes, más una nueva carpeta compartida para logs. Copia los logs
   solo si se desea conservarlos; crea `stats.log` de forma controlada.
4. Instala/actualiza Estadísticas Web, selecciona exactamente la misma carpeta
   compartida de logs y verifica que puede leer, escribir y recortar `stats.log`.
5. Comprueba nginx, una visita registrada, la persistencia de SQLite tras
   reiniciar y la página de estadísticas.
6. Solo entonces cambia el despliegue de webs. Descubre por SSH la ruta real de
   la carpeta seleccionada en `/Home/...` y ejecútalo primero en seco:
   `REMOTE_ROOT=/ruta/real ./deploy.sh --check <sitio>`.
7. Si falla cualquier comprobación, restaura los manifiestos, compose y rutas
   anteriores antes de volver a desplegar.

La selección `/Home/...` de Umbrel es una ruta virtual de la UI. Esta rama no
asume cuál es su ruta de sistema accesible mediante SSH; debe observarse en la
versión estable antes de sustituir el destino de `deploy.sh`.
