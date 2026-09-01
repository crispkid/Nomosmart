# syntax=docker/dockerfile:1.7

FROM quay.io/keycloak/keycloak:26.0.8

COPY --chown=keycloak:keycloak keycloak/themes /opt/keycloak/themes
COPY --chown=keycloak:keycloak --chmod=0555 docker/secret-env-entrypoint.sh /opt/nomosmart/secret-env-entrypoint.sh

ENTRYPOINT ["/opt/nomosmart/secret-env-entrypoint.sh", "/opt/keycloak/bin/kc.sh"]
CMD ["start"]
