# open-murata-bms — container image.
# Runs the poll engine + built-in web dashboard (and MQTT/Home Assistant if enabled in config).
# Read-only monitoring by default; see CLAUDE.md safety rules. Multi-arch (works on a Raspberry Pi).

FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim
LABEL org.opencontainers.image.title="open-murata-bms" \
      org.opencontainers.image.description="Murata IJ1101M battery monitor -> web dashboard / MQTT / Home Assistant"
COPY --from=build /install /usr/local
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
# config.yaml is mounted at /config/config.yaml (see docker-compose.yml)
ENTRYPOINT ["omb", "--config", "/config/config.yaml"]
