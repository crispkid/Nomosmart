{{- define "nomosmart.internalCaVolumeMount" -}}
{{- if and .Values.authentication.previousKeysSecretName (not .omitAuthKeys) }}
- name: authentication-keyring
  mountPath: /run/nomosmart-auth-keys
  readOnly: true
{{- end }}
{{- if .Values.authentication.caSecretName }}
- name: authentication-ca
  mountPath: /etc/nomosmart/auth-ca
  readOnly: true
{{- end }}
{{- if .Values.authentication.bootstrapConfiguration }}
- name: authentication-bootstrap
  mountPath: /etc/nomosmart/auth-bootstrap
  readOnly: true
{{- end }}
- name: embedding-capabilities
  mountPath: /etc/nomosmart/embedding-capabilities.json
  subPath: embedding-capabilities.json
  readOnly: true
{{- $files := list }}
{{- if or (eq .Values.rustfs.mode "bundled") .Values.rustfs.external.caSecretName }}
{{- $files = append $files "rustfs-ca.crt" }}
{{- end }}
{{- if or (eq .Values.postgresql.mode "bundled") .Values.postgresql.external.caSecretName }}
{{- $files = append $files "postgresql-ca.crt" }}
{{- end }}
{{- if or (and (eq .Values.redis.mode "bundled") .Values.redis.cluster.enabled) .Values.redis.external.caSecretName }}
{{- $files = append $files "redis-ca.crt" }}
{{- end }}
{{- if or (eq .Values.opensearch.mode "bundled") .Values.opensearch.external.caSecretName }}
{{- $files = append $files "opensearch-ca.crt" }}
{{- end }}
{{- if and (eq .Values.neo4j.mode "external") .Values.neo4j.external.caSecretName }}
{{- $files = append $files "neo4j-ca.crt" }}
{{- end }}
{{- range $file := $files }}
- name: internal-ca
  mountPath: /etc/nomosmart/tls/{{ $file }}
  subPath: {{ $file }}
  readOnly: true
{{- end }}
{{- end -}}

{{- define "nomosmart.internalCaVolume" -}}
{{- if and .Values.authentication.previousKeysSecretName (not .omitAuthKeys) }}
- name: authentication-keyring
  emptyDir: {medium: Memory, sizeLimit: 1Mi}
- name: authentication-old-keys
  secret:
    secretName: {{ .Values.authentication.previousKeysSecretName }}
    defaultMode: 0440
    items:
      - key: {{ .Values.authentication.previousKeysSecretKey }}
        path: keys.json
{{- end }}
{{- if .Values.authentication.caSecretName }}
- name: authentication-ca
  secret:
    secretName: {{ .Values.authentication.caSecretName }}
{{- end }}
{{- if .Values.authentication.bootstrapConfiguration }}
- name: authentication-bootstrap
  configMap:
    name: {{ include "nomosmart.fullname" . }}-auth-bootstrap
{{- end }}
- name: embedding-capabilities
  configMap:
    name: {{ include "nomosmart.fullname" . }}-embedding-capabilities
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
      {{- if eq .Values.postgresql.mode "bundled" }}
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
