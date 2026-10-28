# Build context is repository root. Production and checks share the same lock.
FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY tools/checks/requirements-runtime.lock /tmp/requirements-runtime.lock
RUN python -m pip install --no-cache-dir --no-deps --require-hashes -r /tmp/requirements-runtime.lock && python -m pip check
RUN useradd --uid 1000 --create-home appuser
WORKDIR /app
COPY --chown=1000:1000 backend/main.py .
COPY --chown=1000:1000 backend/auth/*.py ./auth/
COPY --chown=1000:1000 backend/auth/password_blocklist_*.txt backend/auth/password_blocklist_provenance.json ./auth/
COPY --chown=1000:1000 backend/nl2sql/*.py ./nl2sql/
COPY --chown=1000:1000 backend/nl2sql/retrieval/*.py ./nl2sql/retrieval/
COPY --chown=1000:1000 backend/storage/*.py ./storage/
COPY --chown=1000:1000 backend/workspace/*.py ./workspace/
COPY --chown=1000:1000 backend/analysis/*.py ./analysis/
COPY --chown=1000:1000 backend/preferences/*.py ./preferences/
COPY --chown=1000:1000 backend/migrations/*.sql ./migrations/
USER 1000:1000
CMD ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"]
