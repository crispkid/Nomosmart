# syntax=docker/dockerfile:1.7

FROM rustfs/rustfs:1.0.0-beta.10

COPY --chown=10001:10001 --chmod=0555 docker/secret-env-entrypoint.sh /opt/nomosmart/secret-env-entrypoint.sh

ENTRYPOINT ["/opt/nomosmart/secret-env-entrypoint.sh", "/entrypoint.sh", "rustfs"]
CMD ["/data"]
