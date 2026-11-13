/** Model form, provider and pairing helpers shared by the system workspace (OPT424-038). */
import type { AIModelResponse } from "@/lib/api";
import type { TranslationKey } from "@/lib/i18nClient";
import { UiValidationError } from "@/lib/transportError";
import type { ModelRow } from "./modalState";

export type ModelDeleteDependency = { type: string; count: number };

export function modelRow(model: AIModelResponse): ModelRow {
  return { id: model.id, name: model.name, type: model.model_type, provider: model.provider, endpoint: model.endpoint, default: model.is_default, status: model.is_active ? "active" : "inactive", raw: model };
}

export const aiProviders = [
  { id: "OpenAI", label: "OpenAI" },
  { id: "Gemini", label: "Gemini" },
  { id: "Claude", label: "Claude / Anthropic" },
  { id: "Ollama", label: "Ollama" },
  { id: "vLLM", label: "vLLM" },
  { id: "Custom", label: "Custom / Generic HTTP" }
];

export function normalizedProvider(provider?: string | null) {
  const found = aiProviders.find((item) => item.id.toLowerCase() === (provider ?? "").toLowerCase());
  if (found) return found.id;
  if ((provider ?? "").toLowerCase() === "anthropic") return "Claude";
  return provider ? "Custom" : "OpenAI";
}

export const nativePdfLimitFields = ["max_input_bytes", "max_request_bytes", "max_response_bytes", "context_window", "min_output_tokens", "max_output_tokens"] as const;

export function nativePdfProfile(model: ModelRow | undefined): Record<string, unknown> {
  const value = model?.raw?.config?.native_pdf;
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function nativePdfConfigFromForm(form: FormData, existing: ModelRow | undefined, advanced: unknown): Record<string, unknown> | null {
  const numeric = Object.fromEntries(nativePdfLimitFields.map((key) => [key, String(form.get(`native_pdf_${key}`) ?? "").trim()]));
  const hasInput = Object.values(numeric).some(Boolean);
  if (!hasInput && existing?.status === "inactive" && form.get("is_active") !== "on" && !advanced) return null;
  if (nativePdfLimitFields.some((key) => !/^\d+$/.test(numeric[key]) || !Number.isSafeInteger(Number(numeric[key])) || Number(numeric[key]) <= 0)) throw new UiValidationError("nativePdfCapabilityInvalid");
  const profile = { ...nativePdfProfile(existing), protocol: "openai_responses", mime_types: ["application/pdf"],
    supports_pdf: form.get("native_pdf_supports_pdf") === "on", count_input_tokens: form.get("native_pdf_count_input_tokens") === "on",
    supports_temperature: form.get("native_pdf_supports_temperature") === "on",
    ...Object.fromEntries(nativePdfLimitFields.map((key) => [key, Number(numeric[key])])) } as Record<string, unknown>;
  if (profile.supports_pdf !== true || profile.count_input_tokens !== true || Number(profile.min_output_tokens) > Number(profile.max_output_tokens)
      || Number(profile.max_output_tokens) >= Number(profile.context_window)) throw new UiValidationError("nativePdfCapabilityInvalid");
  if (advanced !== undefined) {
    if (!advanced || typeof advanced !== "object" || Array.isArray(advanced)) throw new UiValidationError("nativePdfConfigConflict");
    const values = advanced as Record<string, unknown>;
    for (const key of [...nativePdfLimitFields, "protocol", "mime_types", "supports_pdf", "count_input_tokens", "supports_temperature"]) {
      if (key in values && JSON.stringify(values[key]) !== JSON.stringify(profile[key])) throw new UiValidationError("nativePdfConfigConflict");
    }
    return { ...profile, ...values, ...Object.fromEntries([...nativePdfLimitFields, "protocol", "mime_types", "supports_pdf", "count_input_tokens", "supports_temperature"].map((key) => [key, profile[key]])) };
  }
  return profile;
}

export function pairedEmbeddingModelIds(model: ModelRow | undefined) {
  const value = model?.raw?.config?.paired_embedding_model_ids;
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : [];
}

export const secretConfigKeys = new Set(["api_key", "apikey", "secret", "password", "credential", "authorization", "access_token", "refresh_token", "bearer_token", "auth_token"]);

export function containsSecretConfigKey(value: unknown): boolean {
  if (Array.isArray(value)) return value.some((item) => containsSecretConfigKey(item));
  if (!value || typeof value !== "object") return false;
  return Object.entries(value).some(([key, item]) => {
    const normalizedKey = key.toLowerCase().replaceAll("-", "_");
    return secretConfigKeys.has(normalizedKey) || normalizedKey.endsWith("_secret") || normalizedKey.endsWith("_api_key") || containsSecretConfigKey(item);
  });
}

export function modelConfigValue(model: ModelRow | undefined, key: string, fallback = "") {
  const value = model?.raw?.config?.[key];
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean" ? String(value) : fallback;
}

export const nativePdfLimitLabels: Record<typeof nativePdfLimitFields[number], TranslationKey> = {
  max_input_bytes: "nativePdfMaxInput", max_request_bytes: "nativePdfMaxRequest", max_response_bytes: "nativePdfMaxResponse",
  context_window: "nativePdfContext", min_output_tokens: "nativePdfMinOutput", max_output_tokens: "nativePdfMaxOutput"
};

export function providerNeedsCredential(provider: string) {
  return provider === "OpenAI" || provider === "Gemini" || provider === "Claude";
}

export function providerHelpKey(provider: string): TranslationKey {
  if (provider === "OpenAI") return "systemProviderHelpOpenAI";
  if (provider === "Gemini") return "systemProviderHelpGemini";
  if (provider === "Claude") return "systemProviderHelpClaude";
  if (provider === "Ollama") return "systemProviderHelpOllama";
  if (provider === "vLLM") return "systemProviderHelpVllm";
  return "systemProviderHelpCustom";
}
