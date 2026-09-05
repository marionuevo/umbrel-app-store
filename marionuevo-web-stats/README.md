# Estadísticas Web

Lee el log de nginx de la app **Nginx Md** y saca estadísticas de visitas y
tráfico de los cinco sitios, casi en tiempo real.

## Por qué hace falta tocar nginx

El tráfico entra así:

    Internet → Cloudflare Tunnel → cloudflared → Nginx Proxy Manager → Nginx Md

NPM reescribe `X-Forwarded-For` con su propio `$remote_addr`, así que para
cuando la petición llega a Nginx Md **todas las visitas parecen venir de
`10.21.0.1`**, la pasarela de Docker. Sin arreglarlo no hay visitantes únicos,
ni países, ni forma de distinguir a una persona de un bot por su origen.

Lo que sí sobrevive intacto es `CF-Connecting-IP`, que pone Cloudflare en el
borde: nginx reenvía los headers que no conoce sin tocarlos. `00-stats.conf`
lo aprovecha con `real_ip_header`, y de paso Cloudflare regala el país en
`CF-IPCountry`, así que la geografía sale sin base de datos de geolocalización.

## Las dos piezas

**En `websites/config/nginx/conf.d/`** (repo `websites`):

- `00-stats.conf` — recupera la IP real y define el formato `stats`, una línea
  JSON por petición. Solo se fía del header si la conexión viene de
  `10.21.0.0/16`, la red de Docker del Umbrel.
- Cada vhost tiene un segundo `access_log … stats;` que escribe a
  `/var/log/nginx/stats.log`. El log combinado de cada sitio se queda como
  estaba.

**Aquí**: el servicio que sigue ese fichero, lo mete en SQLite y sirve el panel.

## Decisiones que no son obvias

- **Solo biblioteca estándar.** Sin dependencias no hay `pip install` que se
  rompa; la imagen son ~50 MB y arranca sin red.
- **Filas crudas, sin tablas de resumen.** A ~4.000 peticiones/día, 180 días son
  ~700.000 filas y SQLite agrega eso en milisegundos. Las tablas de resumen solo
  añadirían sitios donde equivocarse.
- **El seguidor recorta el log él mismo.** `nginx:alpine` no trae logrotate y
  desde aquí no se le puede mandar un `USR1`. Cuando `stats.log` pasa de
  `WEBSTATS_MAX_LOG_MB` y ya está todo ingerido, se trunca en sitio: nginx lo
  abrió en `O_APPEND`, así que su siguiente escritura vuelve sola al offset 0.
  Se pierde lo que se escriba en la ventana entre el `read()` y el `truncate()`
  — microsegundos, a este volumen.
- **Recuerda por dónde iba.** Guarda `(inodo, offset)`, así que un reinicio no
  reprocesa lo leído ni se salta lo que entró mientras estaba parado.
- **Las fotos no son páginas.** Una galería de 31 fotos es 1 página vista, no 32.
- **Tres tipos de tráfico**: personas, bots (se declaran) y sondeos (piden
  `.php`, `.env`, `wp-admin`… en unas webs que son HTML y fotos). En estos
  sitios lo no humano ronda el 25%, así que mezclarlo falsearía todo.

## Ajustes

| Variable | Por defecto | Para qué |
|---|---|---|
| `WEBSTATS_LOG` | `/logs/stats.log` | El log a seguir |
| `WEBSTATS_DB` | `/data/webstats.db` | La base |
| `WEBSTATS_RETENTION_DAYS` | `180` | Se purga lo más viejo cada hora |
| `WEBSTATS_MAX_LOG_MB` | `256` | Umbral de recorte del log |
| `WEBSTATS_HOSTS` | — | Dominios propios: su referer es navegación interna. Se completa solo con los hosts ya servidos |
| `WEBSTATS_LIVE_WINDOW_MIN` | `5` | Ventana de "ahora mismo" |

## Publicar una versión nueva

Sube la versión en `umbrel-app.yml` y haz push a `main`: el workflow construye
y publica `ghcr.io/marionuevo/webstats` para amd64 y arm64. El paquete hereda la
visibilidad pública del repo, así que el Umbrel lo descarga sin credenciales.

Luego fija el digest nuevo en `docker-compose.yml` — el workflow lo deja escrito
en el resumen de la ejecución. La etiqueta puede reapuntar; el digest no.

## Lo que no cubre

- **Los 301 de `2stops.com` → `www.2stops.com` no aparecen**: los resuelve NPM y
  nunca llegan a Nginx Md. La petición que sí llega, la del destino, sí cuenta.
- **Visitantes únicos son IPs distintas**, no personas. Una IP compartida cuenta
  como uno; alguien con IP dinámica cuenta como varios.
- Quien pueda conectarse desde `10.21.0.0/16` puede falsear su IP registrada
  poniendo su propio `CF-Connecting-IP`. Para un panel de estadísticas es un
  riesgo asumible; se acota manteniendo el rango de confianza estrecho.
