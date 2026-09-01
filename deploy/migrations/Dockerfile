# syntax=docker/dockerfile:1.7

FROM flyway/flyway:13.0.0-alpine

RUN addgroup -S -g 10001 nomosmart \
  && adduser -S -D -h /home/nomosmart -u 10001 -G nomosmart nomosmart

COPY sql/migrations /flyway/sql
COPY --chmod=0555 deploy/docker/secret-env-entrypoint.sh /opt/nomosmart/secret-env-entrypoint.sh

ENV HOME=/home/nomosmart
USER 10001:10001
ENTRYPOINT ["/opt/nomosmart/secret-env-entrypoint.sh", "flyway"]
