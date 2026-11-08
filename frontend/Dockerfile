# syntax=docker/dockerfile:1.7

# CHG-294 R2: Node's bundled crypto and Alpine's crypto are separate repair targets.
FROM node:24.21.0-alpine3.24@sha256:be80f76cf40ec8e42b9bec49f60a55e0660f30af58d3e5a25530785b30ea67e2 AS base
RUN apk add --no-cache --upgrade \
    openssl=3.5.9-r0 libssl3=3.5.9-r0 libcrypto3=3.5.9-r0 zlib=1.4-r0 musl-utils=1.2.6-r3

# CHG-301 R2: repair npm's own bundled dependencies, not application locks.
ADD --checksum=sha256:dd77c48eb845f4856c2cdba347cfb52bd877a2655a1ea48ff0c4796e3df9dd7b https://registry.npmjs.org/npm/-/npm-11.21.1.tgz /tmp/npm-11.21.1.tgz
ADD --checksum=sha256:29c4b8e0b2d86cb8795571c1959012ce057a14ecfd34858335f47c31e770a04f https://registry.npmjs.org/undici/-/undici-6.29.1.tgz /tmp/undici-6.29.1.tgz
RUN npm install --global --ignore-scripts --no-audit --no-fund /tmp/npm-11.21.1.tgz \
    && node -e "if(require('/usr/local/lib/node_modules/npm/node_modules/undici/package.json').version !== '6.29.0') process.exit(1)" \
    && rm -rf /usr/local/lib/node_modules/npm/node_modules/undici \
    && mkdir /usr/local/lib/node_modules/npm/node_modules/undici \
    && tar -xzf /tmp/undici-6.29.1.tgz --strip-components=1 -C /usr/local/lib/node_modules/npm/node_modules/undici \
    && node -e "const p=require('/usr/local/lib/node_modules/npm/node_modules/undici/package.json'); if(p.name !== 'undici' || p.version !== '6.29.1' || Object.keys(p.dependencies || {}).length) process.exit(1)" \
    && rm /tmp/npm-11.21.1.tgz /tmp/undici-6.29.1.tgz \
    && npm cache clean --force

FROM base AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM base AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM base AS prod-deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

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
