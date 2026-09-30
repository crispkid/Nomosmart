# syntax=docker/dockerfile:1.7

FROM rustfs/rustfs:1.0.0-beta.10@sha256:60f4f2f41ce95216f8cac676e69f9d90c0bfec458a3bc7fd7fb9b7c2452ac57a

USER 0
RUN apk add --no-cache --upgrade \
    su-exec=0.3-r0 \
    curl=8.22.0-r0 libcurl=8.22.0-r0 \
    libssl3=3.5.8-r0 libcrypto3=3.5.8-r0
COPY --chmod=0555 docker/secret-env-entrypoint.sh /opt/nomosmart/secret-env-entrypoint.sh
COPY --chmod=0555 docker/compose-secret-entrypoint.sh /opt/nomosmart/compose-secret-entrypoint.sh

USER 10001:10001

ENTRYPOINT ["/opt/nomosmart/secret-env-entrypoint.sh", "/entrypoint.sh", "rustfs"]
CMD ["/data"]
