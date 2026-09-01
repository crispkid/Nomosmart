{{- define "nomosmart.internalCaVolumeMount" -}}
- name: internal-ca
  mountPath: /etc/nomosmart/tls
  readOnly: true
{{- end -}}

{{- define "nomosmart.internalCaVolume" -}}
- name: internal-ca
  projected:
    sources:
      {{- if eq .Values.rustfs.mode "bundled" }}
      - secret:
          name: {{ .Values.rustfs.tls.secretName }}
          items:
            - {key: {{ .Values.rustfs.tls.caKey }}, path: rustfs-ca.crt}
      {{- else if .Values.rustfs.external.caSecretName }}
      - secret:
          name: {{ .Values.rustfs.external.caSecretName }}
          items:
            - {key: {{ .Values.rustfs.external.caKey }}, path: rustfs-ca.crt}
      {{- end }}
      {{- if and (eq .Values.postgresql.mode "bundled") .Values.postgresql.operator.enabled }}
      - secret:
          name: {{ .Values.postgresql.tls.secretName }}
          items:
            - {key: {{ .Values.postgresql.tls.caKey }}, path: postgresql-ca.crt}
      {{- else if .Values.postgresql.external.caSecretName }}
      - secret:
          name: {{ .Values.postgresql.external.caSecretName }}
          items:
            - {key: {{ .Values.postgresql.external.caKey }}, path: postgresql-ca.crt}
      {{- end }}
      {{- if and (eq .Values.redis.mode "bundled") .Values.redis.cluster.enabled }}
      - secret:
          name: {{ .Values.redis.tls.secretName }}
          items:
            - {key: {{ .Values.redis.tls.caKey }}, path: redis-ca.crt}
      {{- else if .Values.redis.external.caSecretName }}
      - secret:
          name: {{ .Values.redis.external.caSecretName }}
          items:
            - {key: {{ .Values.redis.external.caKey }}, path: redis-ca.crt}
      {{- end }}
      {{- if eq .Values.opensearch.mode "bundled" }}
      - secret:
          name: {{ .Values.opensearch.tls.secretName }}
          items:
            - {key: {{ .Values.opensearch.tls.caKey }}, path: opensearch-ca.crt}
      {{- else if .Values.opensearch.external.caSecretName }}
      - secret:
          name: {{ .Values.opensearch.external.caSecretName }}
          items:
            - {key: {{ .Values.opensearch.external.caKey }}, path: opensearch-ca.crt}
      {{- end }}
      {{- if and (eq .Values.neo4j.mode "external") .Values.neo4j.external.caSecretName }}
      - secret:
          name: {{ .Values.neo4j.external.caSecretName }}
          items:
            - {key: {{ .Values.neo4j.external.caKey }}, path: neo4j-ca.crt}
      {{- end }}
{{- end -}}
