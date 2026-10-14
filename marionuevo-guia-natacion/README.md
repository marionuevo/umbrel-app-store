# Guía de jornada

Línea de tiempo en directo de una jornada de natación, pensada para el móvil. Las series con los nadadores o clubes elegidos generan un aviso por audio, que llega aunque el móvil esté bloqueado y suene música.

## Cómo funciona

- **Horario:** la jornada (`data/jornada.json`) trae las pruebas, las series, las calles y la duración estimada de cada serie. La hora de cada serie sale de un **ancla**: «la serie *i* empezó en el instante *t*». Sin ancla, la primera serie empieza a la hora oficial (`jornada.inicio`). Las demás se calculan sumando las duraciones y la pausa entre pruebas, hacia delante y hacia atrás.
- **Recolocar el marcador:** desde la web se puede retroceder o adelantar una serie, o tocar una serie y marcar «Esta serie está nadando ahora». El ancla se guarda en `data/estado.json`, así que el cambio queda guardado y todos los dispositivos ven lo mismo. «Volver al horario oficial» quita el ancla.
- **Avisos:** cada 10 s el motor busca las series con interés que están a punto de empezar y manda un `POST {title, message, url}` al webhook de Home Assistant. La automatización `automation.guia_natacion_aviso_por_audio` lo reenvía al iPhone con `interruption-level: time-sensitive`. Con «Anunciar notificaciones» activado, Siri lo lee por los AirPods y baja la música mientras habla.
  - Aviso normal: cuando falta la antelación elegida (3 min por defecto, se cambia en la web). Por ejemplo: «Prueba 1 de 12, serie 12 de 16. Dentro de 2 series. 50 libre. Ana, calle 3. Club Ejemplo: calle 4, Laura Pérez.»
  - La nadadora destacada (`destacada` en la config) tiene además un aviso previo, unos 8 minutos antes (`antelacion_destacada_min`).
  - Cada serie avisa una sola vez. Si se retrasa el marcador y una serie ya avisada vuelve a quedar lejos, volverá a avisar.
- **Interés:** la nadadora destacada y el club destacado entran siempre, tanto en lo que se ve como en lo que avisa. Además hay dos filtros independientes, guardados en el estado: `ver` (qué se destaca en la línea de tiempo y si se ocultan las series sin interés) y `avisar` (qué clubes y nadadores generan aviso).
- **Nombres en el audio:** el nombre de pila y el primer apellido. Las partículas van con la palabra siguiente. Si salen más de dos apellidos, el primero es todo menos el último. Si dos nombres coinciden, se añade el segundo apellido. A la destacada se la nombra por su `alias`.

## Archivos en `data/` (no están en git)

| Archivo | Qué es |
|---|---|
| `config.json` | Webhook de HA, URL de la guía para el aviso, destacada, club destacado, alias de clubes y antelaciones. Modelo en `config.example.json` |
| `jornada.json` | `{jornada: {nombre, inicio (ISO UTC), calles, simulado}, pruebas: [{n, nombre, sexo, pausa_s, series: [{n, duracion_s, calles: {"3": {nombre, año, club, marca, piscina}}}]}]}` |
| `estado.json` | Ancla, filtros, avisos ya enviados e historial. Lo escribe la app |

Las jornadas se generan en `~/AIWork/natacion-liga26-27/` (`scripts/simular_series.py` mientras no haya listas de salida oficiales). Para cambiar de jornada: copiar el nuevo `jornada.json` a `data/` y mandar `estado.json` a la papelera.

## API

`GET api/estado` devuelve todo lo que pinta la web, con las horas de inicio estimadas (`inicios`) y las oficiales (`oficial`) en milisegundos. Las peticiones `POST` son estas:

- `api/ancla` con `{i}`, `{delta: ±1}` o `{oficial: true}`.
- `api/filtros` con `{ver, avisar}`.
- `api/ajustes` con `{avisos_activos, antelacion_min}`.
- `api/prueba`, que manda un aviso de prueba.
