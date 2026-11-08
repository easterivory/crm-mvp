FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home assistant
COPY server.py .
USER assistant
CMD ["uvicorn", "server:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8114", "--no-access-log"]
