# Se construye desde la raíz del repositorio: docker build -t disc-scheduling-api .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# fet-cl (motor FET) en /opt/fet, con su suma de verificación; las bibliotecas de Qt e ICU vienen dentro del paquete
ARG FET_VERSION=7.10.5
ARG FET_SHA256=217ef8f978aeb2df8c7cda3bcb5accb185db3b86fb7f329729d4f93d96bd053c
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libatomic1 libglib2.0-0 \
    && curl -fsSL -o /tmp/fet.tar.gz "https://github.com/nico-alvz/fet-mirror/releases/download/v${FET_VERSION}/fet-cl-${FET_VERSION}-linux-x86_64.tar.gz" \
    && echo "${FET_SHA256}  /tmp/fet.tar.gz" | sha256sum -c - \
    && mkdir /opt/fet && tar xzf /tmp/fet.tar.gz -C /opt/fet --strip-components=1 \
    && rm /tmp/fet.tar.gz \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt .
# uid 1000 coincide con el usuario de Directus para que ambos escriban el mismo archivo SQLite
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 1000 --create-home api \
    && mkdir /data && chown api:api /data
COPY backend/app ./app
COPY db/esquema_plataforma.sql ./db/esquema_plataforma.sql
USER api
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
