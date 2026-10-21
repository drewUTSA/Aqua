FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY tools/checks/requirements-runtime.lock /tmp/requirements-runtime.lock
RUN python -m pip install --no-cache-dir --no-deps --require-hashes -r /tmp/requirements-runtime.lock \
    && python -m pip check
USER 1000:1000
ENTRYPOINT ["/bin/sleep"]
CMD ["300"]
