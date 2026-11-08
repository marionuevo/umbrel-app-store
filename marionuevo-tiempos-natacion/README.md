# Tiempos de natación

Historial de marcas de una nadadora: una fila por cada prueba nadada. Calcula las mejores marcas por piscina, la evolución de cada prueba y el ritmo por parciales de cada carrera, y busca solo los resultados oficiales nuevos.

## Cómo funciona

- **Datos:** `data/nadadas.json` es una lista de nadadas. Cada una lleva `fecha` (`AAAA-MM-DD`, o solo el año si no se sabe), `competicion`, `ciudad`, `piscina` (25, 50 o `null`), `distancia`, `estilo` (`libre`, `espalda`, `braza`, `mariposa`, `estilos`), `tiempo` en segundos, `tipo` (`oficial`, `parcial`, `relevo`, `dsq`), `puesto`, `categoria`, `puestos` (si sale en varias clasificaciones), `puntos`, `parciales` (`[[metros, tiempo acumulado], …]`), `nota` y `origen` (ruta del PDF, `manual` o la importación).
- **Mejores marcas:** solo cuentan las nadadas oficiales, por prueba y por piscina. Los relevos, los parciales y las descalificaciones se guardan pero no son mejor marca.
- **Búsqueda de resultados:** cada `intervalo_min` lista con PROPFIND (`Depth: infinity`) las `carpetas` del owncloud público de la federación. Cada PDF con «result» en el nombre que no se haya leído (o cuyo `etag` haya cambiado) se pasa a texto con `pdftotext -layout` y se buscan los `patrones` de la config. De cada aparición sale la prueba, el tiempo, el puesto y la categoría, los puntos y los parciales. Los parciales se descartan si no acaban en la marca final.
  - Si el PDF cambia (de provisionales a definitivos), se actualizan las nadadas que salieron de él sin tocar la piscina.
  - Una nadada que ya estaba (misma fecha, prueba y tiempo) no se duplica.
  - **Piscina:** los resultados de Splash no dicen la longitud. La app la busca en los PDF de bases de la misma carpeta (INFO, instrucciones, normativa: «Piscina … 25 metros», «50 m y 8 calles»). Si la encuentra, la marca como deducida y la web pide confirmarla; si no, la web pregunta 25 o 50 m para toda la competición.
  - Con nadadas nuevas manda un `POST {title, message, url}` al `webhook` de Home Assistant, por ejemplo «400 libre 5:36.50, mejor marca. 50 mariposa 40.21.».
- **Web:** tres pestañas. **Mejores marcas**: resumen de la temporada y tabla por prueba con la mejor de 25 m, la de 50 m y la de la temporada. **Evolución**: gráfica de cada prueba por fechas, con 25 y 50 m por separado y las mejores marcas en su momento rodeadas. **Historial**: todas las nadadas con filtros por temporada, prueba y piscina, alta manual y exportación a CSV. Al tocar una nadada se abre su ficha: datos, corrección, papelera y, si tiene parciales, la gráfica y la tabla de ritmo cada 50 o 100 m.
- La papelera (`data/papelera.json`) guarda lo que se quita desde la web; «Deshacer» recupera la última.

## Privacidad

El repo es público. Los nombres y las marcas solo están en `data/` del Umbrel (ignorado en git). La web queda detrás del login de Umbrel.

## Archivos en `data/` (no están en git)

| Archivo | Qué es |
|---|---|
| `config.json` | Nombre que se muestra, `patrones` (cómo sale en los PDF, en mayúsculas o no; vale el principio del nombre), owncloud, carpetas, intervalo, webhook y URL de la app. Modelo en `config.example.json` |
| `nadadas.json` | Las nadadas |
| `papelera.json` | Nadadas quitadas desde la web |
| `estado.json` | PDF ya leídos (`revisados`, con su `etag`), última búsqueda, errores y eventos. Lo escribe la app |

## Contenedor

`python:3.13.7-alpine3.22` (la misma imagen que las otras apps). Al arrancar instala `poppler-utils` con `apk` como root y después ejecuta la app como el usuario 1000 (`umbrel`), dueño de `data/`. Si el Umbrel no tiene internet al arrancar, la web funciona pero la búsqueda da error hasta el siguiente reinicio.

## API

| Ruta | Qué hace |
|---|---|
| `GET api/datos` | Nombre, nadadas, tamaño de la papelera y estado de la búsqueda |
| `GET api/csv` | Todas las nadadas en CSV (`;`, UTF-8 con BOM para Numbers y Excel) |
| `POST api/nadada` | Con `id`, corrige esos campos; sin `id`, añade una nadada (`fecha`, `distancia`, `estilo` y `tipo` obligatorios) |
| `POST api/papelera` `{id}` | Mueve la nadada a la papelera |
| `POST api/restaurar` | Recupera la última nadada de la papelera |
| `POST api/competicion` `{fecha, competicion, piscina}` | Pone la piscina a todas las nadadas de esa competición |
| `POST api/buscar` | Busca resultados nuevos ya |

## Probar en local

```sh
python3 tiempos.py --leer resultados.pdf "APELLIDO APELLIDO, A"        # lector de PDF
TIEMPOS_DATA=/tmp/datos TIEMPOS_PUERTO=8765 python3 tiempos.py         # web y búsqueda
```
