FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt && \
    useradd --uid 10001 --create-home relay && \
    mkdir /data && chown relay:relay /data && chmod 700 /data
COPY . /srv/postback_gateway/
USER relay
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["uvicorn", "postback_gateway.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log", "--no-proxy-headers", "--limit-concurrency", "100"]
