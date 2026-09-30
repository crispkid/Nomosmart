{{- define "nomosmart.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Legacy fallback with a copied, field-wise Beat override. Never mutate Worker. */}}
{{- define "nomosmart.beatResources" -}}
{{- $resources := deepCopy .Values.worker.resources -}}
{{- $override := .Values.beat.resources | default dict -}}
{{- mergeOverwrite $resources (deepCopy $override) | toYaml -}}
{{- end -}}

{{/* Explicit defaults also cover old releases upgraded with --reuse-values. */}}
{{- define "nomosmart.publicApiEnabled" -}}
{{- $enabled := true -}}
{{- if hasKey .Values.ingress "publicApi" -}}
{{- if hasKey .Values.ingress.publicApi "enabled" -}}
{{- $enabled = .Values.ingress.publicApi.enabled -}}
{{- end -}}
{{- end -}}
{{- if and .Values.ingress.enabled $enabled -}}true{{- else -}}false{{- end -}}
{{- end -}}

{{- define "nomosmart.componentName" -}}
{{- printf "%s-%s" (include "nomosmart.fullname" .root) .component | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Per-file settings are authoritative; the finite transport envelope is separate.
No values.yaml default for documentUpload: explicit null must fail schema validation,
and older --reuse-values releases must derive the same effective default. */}}
{{- define "nomosmart.documentUploadRequestMiB" -}}
{{- $file := "100" -}}
{{- if hasKey .Values.backend.env "NOMOSMART_DOCUMENT_MAX_UPLOAD_SIZE_MB" -}}
{{- $file = .Values.backend.env.NOMOSMART_DOCUMENT_MAX_UPLOAD_SIZE_MB -}}
{{- else if hasKey .Values.backend.env "MAX_UPLOAD_SIZE_MB" -}}
{{- $file = .Values.backend.env.MAX_UPLOAD_SIZE_MB -}}
{{- end -}}
{{- if not (kindIs "string" $file) -}}
{{- fail "document upload file limit must be an integer environment string" -}}
{{- end -}}
{{- if not (regexMatch "^[1-9][0-9]{0,4}$" $file) -}}
{{- fail "document upload file limit must be an integer in 1..10240 MiB" -}}
{{- end -}}
{{- if gt (int $file) 10240 -}}{{- fail "document upload file limit exceeds 10240 MiB" -}}{{- end -}}
{{- $minimum := add (int $file) 1 -}}
{{- $request := $minimum -}}
{{- if hasKey .Values.ingress "documentUpload" -}}
{{- if hasKey .Values.ingress.documentUpload "requestMaxSizeMiB" -}}
{{- $request = .Values.ingress.documentUpload.requestMaxSizeMiB -}}
{{- end -}}
{{- end -}}
{{- if or (lt (int $request) (int $minimum)) (gt (int $request) 10241) -}}
{{- fail "document upload request limit must be at least file limit + 1 MiB and at most 10241 MiB" -}}
{{- end -}}
{{- printf "%dm" (int $request) -}}
{{- end -}}

{{- define "nomosmart.postgresqlHost" -}}
{{- if and (eq .Values.postgresql.mode "bundled") .Values.postgresql.operator.enabled -}}
{{- printf "%s-postgresql-rw" (include "nomosmart.fullname" .) -}}
{{- else if eq .Values.postgresql.mode "bundled" -}}
{{- printf "%s-postgresql" (include "nomosmart.fullname" .) -}}
{{- else -}}
{{- .Values.postgresql.external.host -}}
{{- end -}}
{{- end -}}

{{/* R23: one validated source for both app processes; old reuse-values supported. */}}
{{- define "nomosmart.uploadSettings" -}}
{{- $request := include "nomosmart.documentUploadRequestMiB" . | trimSuffix "m" -}}
{{- $values := dict "DOCUMENT_UPLOAD_REQUEST_MAX_SIZE_MB" $request "NOMOSMART_UPLOAD_MAX_INFLIGHT" "2" "NOMOSMART_UPLOAD_IO_CHUNK_KIB" "64" "NOMOSMART_UPLOAD_METADATA_MAX_KIB" "1024" "NOMOSMART_UPLOAD_PART_HEADER_MAX_KIB" "16" "NOMOSMART_UPLOAD_IDLE_TIMEOUT_SECONDS" "60" "NOMOSMART_UPLOAD_TOTAL_TIMEOUT_SECONDS" "600" "NOMOSMART_UPLOAD_SCRATCH_MAX_MIB" "256" "NOMOSMART_UPLOAD_SCRATCH_DIR" "/var/lib/nomosmart-upload/private" -}}
{{- $ranges := dict "NOMOSMART_UPLOAD_MAX_INFLIGHT" (list 1 16) "NOMOSMART_UPLOAD_IO_CHUNK_KIB" (list 4 1024) "NOMOSMART_UPLOAD_METADATA_MAX_KIB" (list 64 4096) "NOMOSMART_UPLOAD_PART_HEADER_MAX_KIB" (list 4 64) "NOMOSMART_UPLOAD_IDLE_TIMEOUT_SECONDS" (list 5 600) "NOMOSMART_UPLOAD_TOTAL_TIMEOUT_SECONDS" (list 10 3600) "NOMOSMART_UPLOAD_SCRATCH_MAX_MIB" (list 18 163872) -}}
{{- range $key, $value := $values -}}
{{- if hasKey $.Values.backend.env $key -}}
{{- $configured := index $.Values.backend.env $key -}}
{{- if not (kindIs "string" $configured) -}}{{- fail (printf "%s must be an environment string" $key) -}}{{- end -}}
{{- if and (eq $key "DOCUMENT_UPLOAD_REQUEST_MAX_SIZE_MB") (ne $configured $request) -}}{{- fail "Upload request limit must match ingress.documentUpload.requestMaxSizeMiB" -}}{{- end -}}
{{- $_ := set $values $key $configured -}}
{{- end -}}
{{- end -}}
{{- range $key, $bounds := $ranges -}}
{{- $value := index $values $key -}}
{{- if or (not (regexMatch "^[0-9]{1,6}$" $value)) (lt (int $value) (index $bounds 0)) (gt (int $value) (index $bounds 1)) -}}
{{- fail (printf "%s is outside its bounded upload range" $key) -}}
{{- end -}}
{{- end -}}
{{- if lt (int $values.NOMOSMART_UPLOAD_SCRATCH_MAX_MIB) (int (add (mul (int $request) (int $values.NOMOSMART_UPLOAD_MAX_INFLIGHT)) 16)) -}}{{- fail "Upload scratch must cover all slots plus 16 MiB" -}}{{- end -}}
{{- if lt (int $values.NOMOSMART_UPLOAD_TOTAL_TIMEOUT_SECONDS) (int $values.NOMOSMART_UPLOAD_IDLE_TIMEOUT_SECONDS) -}}{{- fail "Upload total timeout must not be shorter than idle timeout" -}}{{- end -}}
{{- if gt (int $values.NOMOSMART_UPLOAD_PART_HEADER_MAX_KIB) (int $values.NOMOSMART_UPLOAD_METADATA_MAX_KIB) -}}{{- fail "Upload part header cannot exceed metadata budget" -}}{{- end -}}
{{- if not (regexMatch "^/var/lib/nomosmart-upload/[A-Za-z0-9_-]+$" $values.NOMOSMART_UPLOAD_SCRATCH_DIR) -}}{{- fail "Upload scratch must be a private child of its dedicated disk mount" -}}{{- end -}}
{{- range $key, $value := $.Values.frontend.env -}}
{{- if hasKey $values $key -}}
{{- if ne $value (index $values $key) -}}{{- fail (printf "%s must match the shared Backend upload configuration" $key) -}}{{- end -}}
{{- end -}}
{{- end -}}
{{- toJson $values -}}
{{- end -}}

{{- define "nomosmart.runtimeSecretName" -}}
{{- include "nomosmart.secretName" . -}}
{{- end -}}

{{- define "nomosmart.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "nomosmart.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "nomosmart.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "nomosmart.selectorLabels" -}}
app.kubernetes.io/name: {{ include "nomosmart.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "nomosmart.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "nomosmart.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "nomosmart.haAffinity" -}}
podAntiAffinity:
  requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchLabels:
          app.kubernetes.io/name: {{ include "nomosmart.name" .root }}
          app.kubernetes.io/instance: {{ .root.Release.Name }}
          app.kubernetes.io/component: {{ .component }}
      topologyKey: {{ .root.Values.highAvailability.topologyKey }}
{{- end -}}

{{- define "nomosmart.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "nomosmart.fullname" .) -}}
{{- end -}}
{{- end -}}

{{- define "nomosmart.runtimeSecretEnv" -}}
{{- range $key := list "APP_ENCRYPTION_KEY" "DATABASE_URL" "REDIS_URL" "REDIS_SENTINEL_PASSWORD" "CELERY_BROKER_URL" "CELERY_RESULT_BACKEND" "S3_ACCESS_KEY_ID" "S3_SECRET_ACCESS_KEY" "OPENSEARCH_PASSWORD" "NEO4J_PASSWORD" "OIDC_CLIENT_SECRET" "KEYCLOAK_SYNC_CLIENT_SECRET" }}
- name: {{ $key }}
  valueFrom:
    secretKeyRef:
      name: {{ include "nomosmart.secretName" $ }}
      key: {{ $key }}
{{- end }}
{{- end -}}

{{- define "nomosmart.runtimeSecretVolumeMount" -}}
- name: runtime-secret
  mountPath: {{ printf "/var/run/nomosmart-secrets/%s" (include "nomosmart.secretName" .) | quote }}
  readOnly: true
{{- end -}}

{{- define "nomosmart.runtimeSecretVolume" -}}
- name: runtime-secret
  secret:
    secretName: {{ include "nomosmart.secretName" . }}
    defaultMode: 0400
{{- end -}}

{{/*
CHG-248 installer stage boundaries. "operational" preserves ordinary Helm
installs; the guided installer uses "foundation" before any application
workload, and "application" for the one-shot migration/bootstrap revision.
*/}}
{{- define "nomosmart.applicationStageEnabled" -}}
{{- $stage := default "operational" .Values.installer.deploymentStage -}}
{{- if or (eq $stage "application") (eq $stage "operational") -}}true{{- end -}}
{{- end -}}

{{- define "nomosmart.applicationJobsEnabled" -}}
{{- $stage := default "operational" .Values.installer.deploymentStage -}}
{{- if and (eq $stage "application") (not .Values.bootstrap.finalize.enabled) -}}true{{- end -}}
{{- end -}}
