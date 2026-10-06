FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir '.[clickhouse]'
RUN useradd --create-home --uid 10001 tervik && mkdir -p /app/.data && chown -R tervik:tervik /app
USER tervik
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
