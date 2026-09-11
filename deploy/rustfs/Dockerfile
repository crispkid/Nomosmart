# syntax=docker/dockerfile:1.7

FROM rustfs/rustfs:1.0.0-beta.10

USER 0
RUN apk add --no-cache su-exec
COPY --chmod=0555 docker/secret-env-entrypoint.sh /opt/nomosmart/secret-env-entrypoint.sh

ENV NOMOSMART_RUN_AS=10001:10001
ENV NOMOSMART_COPY_DIRS=/opt/rustfs-tls:/run/nomosmart/rustfs-tls

ENTRYPOINT ["/opt/nomosmart/secret-env-entrypoint.sh", "/entrypoint.sh", "rustfs"]
CMD ["/data"]
