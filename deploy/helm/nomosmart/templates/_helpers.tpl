{{- define "nomosmart.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "nomosmart.componentName" -}}
{{- printf "%s-%s" (include "nomosmart.fullname" .root) .component | trunc 63 | trimSuffix "-" -}}
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
