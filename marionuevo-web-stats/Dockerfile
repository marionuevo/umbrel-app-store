FROM python:3.13-alpine

# El servicio entero es biblioteca estándar: no hay pip install que se pueda
# romper, ni ruedas que compilar, ni red necesaria al construir. La imagen sale
# en unos 50 MB y arranca en frío.
WORKDIR /app
COPY src/webstats ./webstats

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WEBSTATS_LOG=/logs/stats.log \
    WEBSTATS_DB=/data/webstats.db \
    WEBSTATS_PORT=8080

EXPOSE 8080

# Corre como root a propósito: nginx crea stats.log con dueño root y modo 644,
# y para recortarlo cuando crece (no hay logrotate en nginx:alpine) hace falta
# permiso de escritura sobre ese fichero.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/salud',timeout=4).status==200 else 1)"

CMD ["python", "-m", "webstats"]
