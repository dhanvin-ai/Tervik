FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir '.[clickhouse]'
RUN useradd --create-home --uid 10001 tervik && mkdir -p /app/.data && chown -R tervik:tervik /app
USER tervik
EXPOSE 8000
# Hosts such as Railway pick the port through $PORT; 8000 otherwise.
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
