# Build context is repository root. Production and checks share the same lock.
FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY tools/checks/requirements-runtime.lock /tmp/requirements-runtime.lock
RUN python -m pip install --no-cache-dir --no-deps --require-hashes -r /tmp/requirements-runtime.lock && python -m pip check
RUN useradd --uid 1000 --create-home appuser
RUN install -d -o 1000 -g 1000 -m 0700 /run/aqua-mail-physical
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
COPY --chown=1000:1000 backend/account/*.py ./account/
COPY --chown=1000:1000 backend/privacy/*.py ./privacy/
COPY --chown=1000:1000 backend/retirement/*.py ./retirement/
COPY --chown=1000:1000 backend/companion/*.py ./companion/
COPY --chown=1000:1000 backend/bank_demo/*.py ./bank_demo/
# Exact SDK-free fictional report core; no MCP transport, eval runner or corpus.
COPY --chown=1000:1000 mcp_demo/__init__.py mcp_demo/data.py mcp_demo/protocol.py mcp_demo/reports.py mcp_demo/guidance.py mcp_demo/web.py ./mcp_demo/
COPY --chown=1000:1000 mcp_demo/fixtures/bank.json ./mcp_demo/fixtures/
COPY --chown=1000:1000 eval/__init__.py ./eval/
COPY --chown=1000:1000 eval/banking/__init__.py eval/banking/catalog.py eval/banking/data.py eval/banking/knowledge.py eval/banking/proposals.py eval/banking/reports.py eval/banking/scope.py ./eval/banking/
COPY --chown=1000:1000 backend/migrations/*.sql ./migrations/
USER 1000:1000
CMD ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"]
