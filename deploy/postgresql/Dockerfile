# syntax=docker/dockerfile:1.7

FROM postgres:18.4-alpine

COPY --chmod=0555 docker/secret-env-entrypoint.sh /opt/nomosmart/secret-env-entrypoint.sh
COPY --chmod=0555 docker/postgresql-init.sh /docker-entrypoint-initdb.d/10-databases.sh

ENV NOMOSMART_REMAP_SECRETS=1
ENTRYPOINT ["/opt/nomosmart/secret-env-entrypoint.sh", "docker-entrypoint.sh"]
