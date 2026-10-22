# Build the site once, then serve the static files with nginx. The dev
# server (npm run dev) is for local work only.
FROM node:24-alpine AS build
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

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 5173
