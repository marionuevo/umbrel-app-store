# WSTunnel WireGuard

Servidor [wstunnel](https://github.com/erebe/wstunnel) que envuelve el
WireGuard del UDM-Pro dentro de un WebSocket, para conectarse desde redes que
**bloquean todo el UDP** y solo dejan salir HTTP/HTTPS por un proxy — el caso
de la WiFi corporativa `na` (ENAIRE), que además hace **MITM de TLS**.

```
cliente (Mac en "na")
  WireGuard local (Endpoint 127.0.0.1) → wstunnel client
      │  wss://tunnel.marionuevo.com:443
      ▼
  proxy transparente ENAIRE (reescribe el TLS)
      │
      ▼
  Cloudflare edge (pone el TLS) → Cloudflare Tunnel (cloudflared, ya instalado)
      │  http://10.80.20.22:56821   (sin puerto abierto en casa)
      ▼
  este contenedor (wstunnel server) → UDP 172.16.10.10:51820 (WireGuard del UDM)
```

El contenido sigue cifrado por WireGuard de extremo a extremo; wstunnel solo le
da forma de WebSocket. El proxy de ENAIRE ve una conexión TLS a un dominio tuyo
y su volumen, **no** el contenido.

## Requisitos previos

1. **Peer dedicado en el WireGuard del UDM-Pro** (UniFi → VPN → WireGuard).
   Hecho: cliente `ws`, `192.168.4.4/32`. **No reutilizar el del MacBook.**
2. **Cloudflare Tunnel** (app cloudflared) ya instalado y conectado.

## Configuración

### 1. Secreto del path

El secreto es la contraseña que **genera Umbrel** por app (`$APP_PASSWORD`), así
que no vive en el repo (que es público). Tras instalar, léelo para configurar el
cliente:

```sh
ssh umbrel@10.80.20.22 \
  'docker inspect marionuevo-wstunnel_server_1 \
     --format "{{range .Args}}{{println .}}{{end}}" | tail -4'
# la línea tras "--restrict-http-upgrade-path-prefix" es el secreto (-P del cliente)
```

El cliente debe usar ese valor EXACTO en `-P`.

### 2. Public Hostname en el Cloudflare Tunnel

Dashboard de **Cloudflare Zero Trust → Networks → Tunnels → (tu túnel) →
Public Hostname → Add a public hostname**:

- **Subdomain:** `tunnel`   **Domain:** `marionuevo.com`
- **Type:** `HTTP`
- **URL:** `10.80.20.22:56821`

Cloudflare crea solo el CNAME (naranja) de `tunnel.marionuevo.com` y pone el
TLS en el borde. El WebSocket va activado por defecto en Cloudflare Tunnel, no
hay que tocar nada. El keepalive de WireGuard (25 s) mantiene viva la conexión
por debajo del timeout de ~100 s de Cloudflare.

No hace falta abrir puertos en casa ni certificados: el connector sale hacia
Cloudflare por QUIC y este contenedor recibe por `http://10.80.20.22:56821`
(verificado: el connector alcanza ese host).

## Cliente

Ver `~/ClaudeWork/vpn-diag/cliente-na/` (README propio): `na-wg.conf` y
`na-tunnel.sh`.

## Seguridad

El puerto `56821` queda expuesto en la LAN en texto plano (ws), pero para
tunelizar algo hacen falta **dos** cosas: el path secreto (`-P`) y una **clave
WireGuard válida** (el tráfico sigue cifrado por WG). Además `--restrict-to`
impide reenviar a cualquier sitio que no sea `172.16.10.10:51820`.

## Notas

- Imagen `ghcr.io/erebe/wstunnel` **10.7.1**, fijada por digest.
- Headless: no hay interfaz web (el `port: 56821` del manifiesto es informativo;
  el botón "Open" de Umbrel no lleva a ninguna UI).
- El puerto `56821` queda expuesto en la LAN (ws en claro), pero por ahí solo se
  puede reenviar a `172.16.10.10:51820` y hace falta el path secreto; el
  contenido sigue cifrado por WireGuard. El connector de Cloudflare lo alcanza
  por la IP del host.
