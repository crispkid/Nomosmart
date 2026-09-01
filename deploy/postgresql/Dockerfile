# syntax=docker/dockerfile:1.7

FROM postgres:18.4-alpine

COPY --chmod=0555 docker/postgresql-init.sh /docker-entrypoint-initdb.d/10-databases.sh
