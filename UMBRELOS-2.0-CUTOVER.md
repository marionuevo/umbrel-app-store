# Preparación de migración a umbrelOS 2.0

La rama se publicó en `main` y la migración de producción se ejecutó el
2026-09-22 sobre umbrelOS 2.0.0 mediante Umbrel MCP. La copia original de los
logs se conserva para rollback.

## Qué cambia

- Nginx Md deja de fijar rutas `/home/umbrel/...`: en umbrelOS 2.0 se eligen
  tres carpetas desde Ajustes (configuración, sitios y logs).
- Estadísticas Web conserva su base SQLite en `${APP_DATA_DIR}/data`, declara
  ese directorio como `storage.dataRoot`, y selecciona los logs compartidos por
  `folderAccess` en vez de montar el `app-data` de Nginx Md.
- Los ajustes de Estadísticas Web se declaran para su edición desde la UI.
- WSTunnel no tiene datos que migrar; solo adopta la política de reinicio y la
  lectura del secreto ya no depende de un nombre de contenedor fijado.

## Resultado del cutover

1. Nginx Md `1.2.0` is ready with configuration, sites, and logs mounted from
   `/Home/websites` folder selections.
2. Web Stats `1.1.0` is ready with `/Home/websites/logs` mounted at `/logs` and
   `storage.dataRoot: data` enabled.
3. WSTunnel `1.0.2` is ready and remains stateless.
4. The old logs were copied to `/Home/websites/logs`; the original app-managed
   directory remains intact.
5. HTTP serving returned `200`; Web Stats health reached the authenticated
   proxy; all three app operations completed without failure.
6. No external storage move or destructive cleanup has been performed.

Before normal website changes, run `./deploy-config.sh --check` and then
`./deploy.sh --check <sitio>`.

La selección `/Home/...` de Umbrel es una ruta virtual de la UI. En esta
migración `/Home/websites` fue verificado como
`/home/umbrel/umbrel/home/websites` para las herramientas SSH.
