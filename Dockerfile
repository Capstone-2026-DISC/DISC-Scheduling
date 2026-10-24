# Se construye desde la raíz del repositorio: docker build -t disc-scheduling-api .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt .
# uid 1000 coincide con el usuario de Directus para que ambos escriban el mismo archivo SQLite
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 1000 --create-home api \
    && mkdir /data /satelites && chown api:api /data /satelites
COPY backend/app ./app
COPY db/esquema_plataforma.sql ./db/esquema_plataforma.sql
USER api
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
