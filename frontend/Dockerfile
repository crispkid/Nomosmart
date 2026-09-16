# syntax=docker/dockerfile:1.7

# CHG-294 R2: Node's bundled crypto and Alpine's crypto are separate repair targets.
FROM node:24.21.0-alpine3.24@sha256:be80f76cf40ec8e42b9bec49f60a55e0660f30af58d3e5a25530785b30ea67e2 AS base
RUN apk add --no-cache --upgrade \
    openssl=3.5.8-r0 libssl3=3.5.8-r0 libcrypto3=3.5.8-r0

# CHG-301 R2: repair npm's own bundled dependencies, not application locks.
ADD --checksum=sha256:9f58bff01604cb1b14008fef14dceb14d836a49225e45c6c2e37de3be3e707f0 https://registry.npmjs.org/npm/-/npm-11.19.1.tgz /tmp/npm-11.19.1.tgz
RUN npm install --global --ignore-scripts --no-audit --no-fund /tmp/npm-11.19.1.tgz \
    && rm /tmp/npm-11.19.1.tgz \
    && npm cache clean --force

FROM base AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM base AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM base AS prod-deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup -S -g 10001 nomosmart \
  && adduser -S -u 10001 nomosmart -G nomosmart \
  && rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx
COPY --from=builder --chown=nomosmart:nomosmart /app/package.json /app/package-lock.json ./
COPY --from=builder --chown=nomosmart:nomosmart /app/.next ./.next
COPY --from=builder --chown=nomosmart:nomosmart /app/public ./public
COPY --from=prod-deps --chown=nomosmart:nomosmart /app/node_modules ./node_modules

USER nomosmart
EXPOSE 3000
CMD ["node", "node_modules/next/dist/bin/next", "start"]
