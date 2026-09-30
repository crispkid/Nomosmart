# syntax=docker/dockerfile:1.7

# CHG-300: official multi-platform index, metadata verified 2026-09-13.
# Runtime/security acceptance still requires a separately approved new build.
FROM flyway/flyway:13.6.0-alpine@sha256:fb7f326765649205574551e25ba774e432ea840b126983d6ec3bbda8f21b137c

RUN addgroup -S -g 10001 nomosmart \
  && adduser -S -D -h /home/nomosmart -u 10001 -G nomosmart nomosmart \
  && apk add --no-cache su-exec

COPY sql/migrations /flyway/sql
COPY --chmod=0555 deploy/docker/secret-env-entrypoint.sh /opt/nomosmart/secret-env-entrypoint.sh
COPY --chmod=0555 deploy/docker/compose-secret-entrypoint.sh /opt/nomosmart/compose-secret-entrypoint.sh

ENV HOME=/home/nomosmart
USER 10001:10001
ENTRYPOINT ["/opt/nomosmart/secret-env-entrypoint.sh", "flyway"]
