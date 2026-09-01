# syntax=docker/dockerfile:1.7

FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:24-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:24-alpine AS prod-deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

FROM node:24-alpine AS runner
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
