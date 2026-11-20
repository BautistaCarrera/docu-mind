FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Sin EXPOSE: el bot no escucha ningún puerto, hace polling saliente hacia
# la API de Telegram. No hay superficie HTTP pública que atacar.
CMD ["python", "-m", "app.bot"]
