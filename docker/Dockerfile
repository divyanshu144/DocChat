# Production images. Two independently deployable targets share one dependency layer:
#   docker build -f docker/Dockerfile --target api    -t docchat-api .
#   docker build -f docker/Dockerfile --target worker -t docchat-worker .
# The root Dockerfile + docker-compose.yml remain the local-development path and are untouched.
ARG PYTHON_IMAGE=python:3.13-slim-bookworm

# ---- build the virtualenv (build tooling never reaches the runtime image) ----
FROM ${PYTHON_IMAGE} AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
COPY requirements.lock /tmp/requirements.lock
# The lock is the exact set that was built and tested; requirements.txt (unpinned, with dev tools) is not used here.
# `pip check` must be clean except two KNOWN metadata conflicts we accept on purpose (see docs/aws/security.md):
#   fastembed caps pillow<13   - only image-embedding models need that; this app embeds text only (verified).
#   python-jose caps pyasn1<0.5 - only its non-cryptography RSA backend uses pyasn1; the app signs HS256.
# Upgrading past these caps is what removes the fixable HIGH/CRITICAL Pillow and jose CVEs from the image.
RUN /opt/venv/bin/pip install --no-deps -r /tmp/requirements.lock \
 && bad="$(/opt/venv/bin/pip check | grep -vE '^(fastembed [0-9.]+ has requirement pillow|python-jose [0-9.]+ has requirement pyasn1)' || true)" \
 && { [ -z "$bad" ] || { echo "unexpected dependency conflict:"; echo "$bad"; exit 1; }; }

# No package manager ships in the runtime image (smaller attack surface; pip's vendored copies of
# urllib3/msgpack are otherwise flagged by scanners and are unreachable from the app anyway).
RUN /opt/venv/bin/python -m pip uninstall -y pip

# ---- shared runtime base ----
FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    FASTEMBED_CACHE_PATH=/opt/fastembed \
    LOG_FORMAT=json
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr libmagic1 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin app
RUN /usr/local/bin/python -m pip uninstall -y pip
COPY --from=builder /opt/venv /opt/venv
# Bake the embedding model so tasks start without internet access to the model host and without a
# writable cache. Must match EMBEDDING_MODEL at runtime.
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
RUN python -c "from fastembed import TextEmbedding; list(TextEmbedding('${EMBEDDING_MODEL}').embed(['warmup']))" \
 && chmod -R a+rX /opt/fastembed
WORKDIR /srv
COPY app ./app
# Fail the build, not the deploy, if the application cannot import.
RUN python -c "import app.main, app.worker.loop"
USER 10001:10001

# ---- API ----
FROM runtime AS api
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=2).status == 200 else 1)"]
# No access log (it records query strings); request telemetry covers it. SIGTERM -> graceful drain.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--timeout-graceful-shutdown", "30"]

# ---- ingestion worker ----
FROM runtime AS worker
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/livez', timeout=2).status == 200 else 1)"]
CMD ["python", "-m", "app.worker"]
