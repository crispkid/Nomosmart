{{- define "nomosmart.bootstrapInitContainer" -}}
- name: deployment-readiness
  image: "{{ .Values.image.backend.repository }}:{{ .Values.image.backend.tag }}"
  imagePullPolicy: {{ .Values.image.backend.pullPolicy }}
  command: ["python", "-m", "app.deployment.bootstrap"]
  args: ["--mode", "check", "--wait-seconds", {{ .Values.bootstrap.waitSeconds | quote }}]
  securityContext:
    {{- toYaml .Values.securityContext | nindent 4 }}
  envFrom:
    - configMapRef:
        name: {{ include "nomosmart.fullname" . }}-config
  env:
    {{- include "nomosmart.runtimeSecretEnv" . | nindent 4 }}
    {{- if ne .Values.bootstrap.deploymentPhase "operational" }}
    - name: BREAK_GLASS_INITIAL_PASSWORD
      valueFrom:
        secretKeyRef:
          name: {{ include "nomosmart.secretName" . }}
          key: {{ .Values.bootstrap.breakGlassPasswordKey }}
    {{- end }}
    - name: DEPLOYMENT_KEYCLOAK_MODE
      value: "verify"
  volumeMounts:
    {{- include "nomosmart.internalCaVolumeMount" . | nindent 4 }}
{{- end -}}

{{- define "nomosmart.bootstrapEvidenceInitContainer" -}}
- name: deployment-evidence
  image: "{{ .Values.image.backend.repository }}:{{ .Values.image.backend.tag }}"
  imagePullPolicy: {{ .Values.image.backend.pullPolicy }}
  command: ["python", "-c"]
  args:
    - |
      import json
      import time
      from app.deployment.bootstrap import (
          BootstrapFailure,
          DeploymentBootstrapSettings,
          _bootstrap_evidence_check,
      )
      settings = DeploymentBootstrapSettings()
      deadline = time.monotonic() + {{ int .Values.bootstrap.waitSeconds }}
      while True:
          try:
              check = _bootstrap_evidence_check(settings)
              print(json.dumps({"status": "ready", "check": check.name}))
              break
          except BootstrapFailure as error:
              if time.monotonic() >= deadline:
                  raise SystemExit(error.code)
              time.sleep(3)
  securityContext:
    {{- toYaml .Values.securityContext | nindent 4 }}
  envFrom:
    - configMapRef:
        name: {{ include "nomosmart.fullname" . }}-config
  env:
    {{- include "nomosmart.runtimeSecretEnv" . | nindent 4 }}
    {{- if ne .Values.bootstrap.deploymentPhase "operational" }}
    - name: BREAK_GLASS_INITIAL_PASSWORD
      valueFrom:
        secretKeyRef:
          name: {{ include "nomosmart.secretName" . }}
          key: {{ .Values.bootstrap.breakGlassPasswordKey }}
    {{- end }}
    - name: DEPLOYMENT_KEYCLOAK_MODE
      value: "verify"
  volumeMounts:
    {{- include "nomosmart.internalCaVolumeMount" . | nindent 4 }}
{{- end -}}

{{- define "nomosmart.backendReadyInitContainer" -}}
- name: backend-readiness
  image: "{{ .Values.image.backend.repository }}:{{ .Values.image.backend.tag }}"
  imagePullPolicy: {{ .Values.image.backend.pullPolicy }}
  command: ["python", "-c"]
  args:
    - |
      import time
      import json
      import urllib.error
      import urllib.request
      from app.core.config import MigrationTargetSettings
      from app.deployment.migration_gate import MigrationGateError, migration_readiness_matches, required_contract
      try:
          settings = MigrationTargetSettings()
          required_contract(settings.migration_required_version, settings.migration_required_checksum, settings.migration_baseline_checksum)
      except (ValueError, MigrationGateError):
          raise SystemExit("database_migration_configuration_invalid")
      url = "http://{{ include "nomosmart.fullname" . }}-backend:{{ .Values.backend.service.port }}/api/v1/ready"
      deadline = time.monotonic() + {{ int .Values.bootstrap.waitSeconds }}
      while True:
          try:
              with urllib.request.urlopen(url, timeout=5) as response:
                  content = response.read(65537)
                  if len(content) <= 65536 and response.status == 200 and migration_readiness_matches(json.loads(content), settings):
                      print('{"status":"ready","check":"backend"}')
                      break
          except (OSError, urllib.error.HTTPError, ValueError):
              pass
          if time.monotonic() >= deadline:
              raise SystemExit("backend_readiness_timeout")
          time.sleep(3)
  securityContext:
    {{- toYaml .Values.securityContext | nindent 4 }}
  envFrom:
    - configMapRef:
        name: {{ include "nomosmart.fullname" . }}-config
{{- end -}}
