FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 1000 --create-home modulo
COPY modulo_app.py .
USER modulo
EXPOSE 8000
CMD ["uvicorn", "modulo_app:app_por_defecto", "--factory", "--host", "0.0.0.0", "--port", "8000"]
