const sensitiveParts = ["password", "otp", "token", "secret", "credential", "api_key", "apikey", "authorization", "bearer", "pkce", "private_key", "refresh"];

export type CapturedSessionDraft = {
  formKey: string;
  payload: Record<string, string | number | boolean | null | Array<string | number | boolean | null>>;
};

export function randomDraftNonce(): string {
  const bytes = new Uint8Array(18);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function captureSessionDraft(): CapturedSessionDraft | null {
  const form = document.querySelector<HTMLElement>("[data-session-draft-key]");
  const formKey = form?.dataset.sessionDraftKey;
  if (!form || !formKey) return null;
  const payload: CapturedSessionDraft["payload"] = {};
  form.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>("[data-session-draft-field]").forEach((field) => {
    const key = field.dataset.sessionDraftField || field.name;
    if (!key || isSensitiveField(key, field)) return;
    if (field instanceof HTMLInputElement && field.type === "file") return;
    if (field instanceof HTMLInputElement && field.type === "checkbox") {
      payload[key] = field.checked;
      return;
    }
    if (field instanceof HTMLInputElement && field.type === "number") {
      payload[key] = Number(field.value);
      return;
    }
    if (field instanceof HTMLSelectElement && field.multiple) {
      payload[key] = Array.from(field.selectedOptions, (option) => option.value);
      return;
    }
    payload[key] = field.value;
  });
  return Object.keys(payload).length ? { formKey, payload } : null;
}

export function isSensitiveField(key: string, field?: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement): boolean {
  const haystack = `${key} ${field?.name ?? ""} ${field?.id ?? ""} ${field instanceof HTMLInputElement ? field.type : ""}`.toLowerCase().replace(/-/g, "_");
  return sensitiveParts.some((part) => haystack.includes(part));
}
