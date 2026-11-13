{{- define "nomosmart.authKeyringInit" -}}
{{- if .Values.authentication.previousKeysSecretName }}
- name: authentication-keyring
  image: "{{ .Values.image.backend.repository }}:{{ .Values.image.backend.tag }}"
  imagePullPolicy: {{ .Values.image.backend.pullPolicy }}
  command: ["python", "-c"]
  args:
    - |
      import os
      from pathlib import Path
      source = Path('/var/run/nomosmart-old-auth-keys/keys.json')
      target = Path('/run/nomosmart-auth-keys/keys.json')
      fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
      with os.fdopen(fd, 'w') as handle:
          handle.write(source.read_text())
      os.chmod(target, 0o600)
  securityContext:
    {{- toYaml .Values.securityContext | nindent 4 }}
  resources:
    requests: {cpu: 25m, memory: 32Mi}
    limits: {cpu: 100m, memory: 128Mi}
  volumeMounts:
    - name: authentication-old-keys
      mountPath: /var/run/nomosmart-old-auth-keys
      readOnly: true
    - name: authentication-keyring
      mountPath: /run/nomosmart-auth-keys
{{- end }}
{{- end -}}
