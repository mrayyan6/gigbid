# Next.js web image (standalone output). Build context is the repo root:
#   docker build -f infra/docker/web.Dockerfile --build-arg API_URL=http://api:8000 .
# next.config.mjs reads API_URL at BUILD time (rewrites are baked into the routes manifest), so
# pass the URL the container will use to reach the API.
FROM node:24-slim AS deps
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
# npm ci fails on Linux with a lockfile written on Windows (missing nested picomatch), so use install
RUN npm install -g npm@11.6.1 && npm install --no-audit --no-fund

FROM node:24-slim AS build
WORKDIR /web
ARG API_URL=http://api:8000
ENV API_URL=${API_URL} \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /web/node_modules ./node_modules
COPY apps/web ./
RUN mkdir -p public && npm run build

FROM node:24-slim AS runtime
WORKDIR /web
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
COPY --from=build /web/.next/standalone ./
COPY --from=build /web/.next/static ./.next/static
COPY --from=build /web/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
