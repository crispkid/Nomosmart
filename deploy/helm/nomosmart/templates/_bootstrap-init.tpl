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
{{- end -}}

{{- define "nomosmart.backendReadyInitContainer" -}}
- name: backend-readiness
  image: "{{ .Values.image.backend.repository }}:{{ .Values.image.backend.tag }}"
  imagePullPolicy: {{ .Values.image.backend.pullPolicy }}
  command: ["python", "-c"]
  args:
    - |
      import time
      import urllib.error
      import urllib.request
      url = "http://{{ include "nomosmart.fullname" . }}-backend:{{ .Values.backend.service.port }}/api/v1/ready"
      deadline = time.monotonic() + {{ int .Values.bootstrap.waitSeconds }}
      while True:
          try:
              with urllib.request.urlopen(url, timeout=5) as response:
                  if response.status == 200:
                      print('{"status":"ready","check":"backend"}')
                      break
          except (OSError, urllib.error.HTTPError):
              pass
          if time.monotonic() >= deadline:
              raise SystemExit("backend_readiness_timeout")
          time.sleep(3)
  securityContext:
    {{- toYaml .Values.securityContext | nindent 4 }}
{{- end -}}
