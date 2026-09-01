ARG OPENSEARCH_BASE_IMAGE=opensearchproject/opensearch:2.19.6@sha256:b6c3071dde7b170d85f3a44b9c4ef1cae2e7a23f47448ffd7a2538524476d864
FROM ${OPENSEARCH_BASE_IMAGE}

RUN /usr/share/opensearch/bin/opensearch-plugin install --batch repository-s3 \
    && /usr/share/opensearch/bin/opensearch-plugin list | grep -Fx repository-s3
