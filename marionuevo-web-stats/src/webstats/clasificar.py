"""Clasificar una petición: quién la hace, con qué, y desde dónde viene.

Todo se resuelve con tablas de expresiones regulares. Un analizador de
user-agent de verdad es una dependencia grande y un problema de mantenimiento;
para cinco webs estáticas basta con reconocer lo que aparece de hecho en el log.
"""

import re
from urllib.parse import urlsplit

# ── Sondeos ──────────────────────────────────────────────────────────────────
# Estas cinco webs son HTML y fotos, y nada más. Cualquier petición de un .php,
# un .env o un panel de administración es un escáner de vulnerabilidades, no un
# visitante ni un buscador. Se listan solo patrones inequívocos: rutas genéricas
# como /admin o /config se dejan fuera a propósito porque podrían ser legítimas
# el día que una web las use.
SONDEO_RE = re.compile(
    r"""
      \.(php\d?|phtml|asp|aspx|jsp|cgi|pl|bak|sql|old|swp|env|key|pem)(?:$|[?/])
    | /\.(env|git|svn|hg|aws|ssh|htpasswd|htaccess)(?:$|[/?])
    | /(wp-admin|wp-login|wp-content|wp-includes|wordpress|xmlrpc)
    | /(phpmyadmin|pma|myadmin|adminer|cpanel|webmail|solr|jenkins|struts)
    | /(vendor|cgi-bin|autodiscover|owa|actuator|telescope|debug)/
    | /etc/passwd
    | (?:^|/)\.\./
    """,
    re.I | re.X,
)

# ── Automatismos ─────────────────────────────────────────────────────────────
# Buscadores, previsualizadores de enlaces, monitores y herramientas de línea de
# comandos. Se declaran, así que se les cree.
BOT_RE = re.compile(
    r"""
      bot\b | \bbots\b | spider | crawl | slurp | scrap
    | \b(curl|wget|libwww|python-requests|python-urllib|go-http-client|okhttp
        |java|apache-httpclient|axios|node-fetch|guzzle|httpx|aiohttp|postman)\b
    | (google|bing|yandex|baidu|duckduck|applebot|petal|seznam|qwant)
    | (facebookexternalhit|whatsapp|telegram|twitterbot|slackbot|discord|embedly)
    | (pingdom|uptimerobot|statuscake|newrelic|datadog|site24x7|zabbix)
    | (ahrefs|semrush|mj12|dotbot|blexbot|serpstat|dataforseo|screaming)
    | (headlesschrome|phantomjs|puppeteer|playwright|selenium)
    | (feedly|feedfetcher|rss|photon|preview|validator|monitor|检索)
    | (gptbot|claudebot|claude-|anthropic|openai|ccbot|perplexity|bytespider|amazonbot)
    """,
    re.I | re.X,
)

# ── Navegadores ──────────────────────────────────────────────────────────────
# El orden importa: casi todos mienten diciendo ser los demás. Edge dice ser
# Chrome, Chrome dice ser Safari, y Safari dice ser Mozilla.
NAVEGADORES = [
    ("Edge", re.compile(r"\bEdge?[A-Z]*/([\d.]+)", re.I)),
    ("Opera", re.compile(r"\b(?:OPR|Opera)/([\d.]+)", re.I)),
    ("Vivaldi", re.compile(r"\bVivaldi/([\d.]+)", re.I)),
    ("Brave", re.compile(r"\bBrave/([\d.]+)", re.I)),
    ("Samsung Internet", re.compile(r"\bSamsungBrowser/([\d.]+)", re.I)),
    ("Firefox", re.compile(r"\b(?:Firefox|FxiOS)/([\d.]+)", re.I)),
    ("Chrome", re.compile(r"\b(?:Chrome|CriOS|Chromium)/([\d.]+)", re.I)),
    ("Safari", re.compile(r"\bVersion/([\d.]+).*\bSafari/", re.I)),
    ("Internet Explorer", re.compile(r"\bMSIE ([\d.]+)|\bTrident/.*\brv:([\d.]+)", re.I)),
]

SISTEMAS = [
    ("iPadOS", re.compile(r"\biPad\b", re.I)),
    ("iOS", re.compile(r"\b(iPhone|iPod)\b", re.I)),
    ("Android", re.compile(r"\bAndroid\b", re.I)),
    ("macOS", re.compile(r"\b(Mac OS X|Macintosh)\b", re.I)),
    ("Windows", re.compile(r"\bWindows NT\b", re.I)),
    ("Chrome OS", re.compile(r"\bCrOS\b", re.I)),
    ("Linux", re.compile(r"\b(Linux|X11|Ubuntu|Fedora|Debian)\b", re.I)),
]

TABLET_RE = re.compile(r"\b(iPad|Tablet|PlayBook|Silk)\b|Android(?!.*\bMobile\b)", re.I)
MOVIL_RE = re.compile(r"\b(Mobile|iPhone|iPod|Android|Windows Phone|IEMobile)\b", re.I)

# ── Procedencia ──────────────────────────────────────────────────────────────
BUSCADORES = (
    "google.", "bing.", "duckduckgo.", "yahoo.", "yandex.", "baidu.", "ecosia.",
    "search.brave.", "startpage.", "qwant.", "search.marcia", "mojeek.",
    "lite.duckduckgo.", "searx",
)
REDES = (
    "facebook.", "instagram.", "t.co", "twitter.", "x.com", "linkedin.",
    "reddit.", "pinterest.", "youtube.", "tiktok.", "whatsapp", "telegram",
    "mastodon", "bsky.", "threads.", "vk.com", "flickr.", "500px.",
)
IA = ("chatgpt.com", "chat.openai.com", "claude.ai", "perplexity.ai", "gemini.google.", "copilot.microsoft.")

# Extensiones que son parte de una página, no una página. Sin esto una galería
# de 31 fotos cuenta como 32 "visitas".
RECURSO_RE = re.compile(
    r"\.(jpe?g|png|gif|webp|avif|svg|ico|bmp|tiff?|heic"
    r"|css|js|mjs|map|json|xml|txt"
    r"|woff2?|ttf|otf|eot"
    r"|mp4|webm|mov|mp3|wav|ogg|m4a"
    r"|zip|pdf)$",
    re.I,
)


def es_pagina(ruta):
    """¿Esto cuenta como una página vista?"""
    limpia = ruta.split("?", 1)[0].rstrip("/") or "/"
    if limpia == "/" or limpia.endswith("/"):
        return True
    if RECURSO_RE.search(limpia):
        return False
    # Sin extensión reconocible se asume página (/sobre-mi, /galeria/2024).
    return True


def tipo_de_visita(ua, ruta):
    """personas / bots / sondeos. En ese orden de comprobación."""
    if SONDEO_RE.search(ruta):
        return "sondeo"
    if not ua or ua == "-":
        # Un navegador siempre se identifica. Un user-agent vacío es alguien
        # que no quiere que se sepa qué es, y eso nunca es una persona.
        return "bot"
    if BOT_RE.search(ua):
        return "bot"
    return "persona"


def navegador(ua):
    if not ua or ua == "-":
        return "", ""
    for nombre, rx in NAVEGADORES:
        m = rx.search(ua)
        if m:
            version = next((g for g in m.groups() if g), "")
            return nombre, version.split(".")[0]
    return "Otro", ""


def sistema(ua):
    if not ua or ua == "-":
        return ""
    for nombre, rx in SISTEMAS:
        if rx.search(ua):
            return nombre
    return "Otro"


def dispositivo(ua):
    if not ua or ua == "-":
        return ""
    if TABLET_RE.search(ua):
        return "tablet"
    if MOVIL_RE.search(ua):
        return "móvil"
    return "escritorio"


def procedencia(referer, host_propio):
    """Devuelve (tipo, dominio). El tipo agrupa; el dominio es para la tabla."""
    if not referer or referer == "-":
        return "directo", ""
    try:
        dominio = (urlsplit(referer).hostname or "").lower()
    except ValueError:
        return "otro", ""
    if not dominio:
        return "directo", ""
    if dominio == (host_propio or "").lower() or dominio in OWN_HOSTS_CACHE:
        return "interno", dominio
    if any(b in dominio for b in BUSCADORES):
        return "buscador", dominio
    if any(r in dominio for r in REDES):
        return "red social", dominio
    if any(i in dominio for i in IA):
        return "IA", dominio
    return "otro", dominio


# Se rellena desde config al arrancar; vive aquí para que procedencia() no
# tenga que recibirlo en cada llamada.
OWN_HOSTS_CACHE = set()


def registrar_hosts_propios(hosts):
    OWN_HOSTS_CACHE.clear()
    for h in hosts:
        h = h.strip().lower()
        if h:
            OWN_HOSTS_CACHE.add(h)
            # www.2stops.com y 2stops.com son la misma casa.
            OWN_HOSTS_CACHE.add(h[4:] if h.startswith("www.") else "www." + h)
