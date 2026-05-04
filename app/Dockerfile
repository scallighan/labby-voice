FROM python:3.12-slim AS base

WORKDIR /app

FROM base AS deps
COPY pyproject.toml .
RUN pip install --no-cache-dir . \
    && rm -rf /root/.cache

FROM base
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
COPY . .

EXPOSE 3978

CMD ["python", "app.py"]
