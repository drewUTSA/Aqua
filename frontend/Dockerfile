# Build the site once, then serve the static files with nginx. The dev
# server (npm run dev) is for local work only.
FROM node:24-alpine@sha256:116b800c3754b440ee0aa3ed2f20f5bf3d99a554bfd9adeea09ea8017f6e85f5 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-fund
COPY . .
# Rebuild the UI alone to roll presentation back without downgrading auth.
# Fail a deployment typo instead of silently building an unintended shell.
ARG AQUA_UI_SHELL=opal
RUN case "$AQUA_UI_SHELL" in opal|legacy) ;; *) echo "Invalid AQUA_UI_SHELL: choose opal or legacy" >&2; exit 1 ;; esac
# Production cannot inherit developer demo or presentation values from env files.
RUN VITE_AQUA_DEMO_MODE=false VITE_AQUA_USE_MOCK=false VITE_AQUA_UI_SHELL="$AQUA_UI_SHELL" npm run build

FROM nginx:1.30.8-alpine@sha256:8eb04fe3b385090e9aa02961f77398ad09b6bf33ab07f6669a5bb7acce22c0d3
# The master and the workers share the unprivileged nginx identity. Keep
# the PID on its bounded tmpfs; Compose gives the cache a separate tmpfs.
RUN rm -f /usr/share/nginx/html/50x.html \
    && sed -i -E '/^[[:space:]]*user[[:space:]]/d; s@^[[:space:]]*pid[[:space:]]+[^;]+;@pid /tmp/nginx.pid;@' /etc/nginx/nginx.conf \
    && grep -Fxq 'pid /tmp/nginx.pid;' /etc/nginx/nginx.conf \
    && test "$(id -u nginx):$(id -g nginx)" = '101:101'
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
COPY 404.html /usr/share/nginx/html/404.html
USER 101:101
EXPOSE 5173
