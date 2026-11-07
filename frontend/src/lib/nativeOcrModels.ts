import type { AIModelResponse } from "@/lib/api";

const nativeLimitKeys = ["max_input_bytes", "max_request_bytes", "max_response_bytes", "context_window", "max_output_tokens", "min_output_tokens"] as const;

/** Mirror require_native_capabilities; the server remains the dispatch authority. */
export function isNativeOcrModel(model: AIModelResponse): boolean {
  if (model.model_type !== "OCR" || model.is_active !== true || model.deleted_at != null
      || model.provider.trim().toLowerCase() !== "openai") return false;
  const config = model.config;
  if (!config || typeof config !== "object" || Array.isArray(config)) return false;
  const profile = config.native_pdf;
  if (!profile || typeof profile !== "object" || Array.isArray(profile)) return false;
  const limits = profile as Record<string, unknown>;
  if (limits.protocol !== "openai_responses" || limits.supports_pdf !== true || limits.count_input_tokens !== true
      || !Array.isArray(limits.mime_types) || !limits.mime_types.length
      || !limits.mime_types.every((mime) => typeof mime === "string") || !limits.mime_types.includes("application/pdf")) return false;
  if (!nativeLimitKeys.every((key) => {
    const value = limits[key];
    return typeof value === "number" && Number.isInteger(value) && value > 0 && value < 2 ** 63;
  })) return false;
  if ((limits.min_output_tokens as number) > (limits.max_output_tokens as number)
      || (limits.max_output_tokens as number) >= (limits.context_window as number)) return false;
  if ("supports_temperature" in limits && typeof limits.supports_temperature !== "boolean") return false;
  if (typeof config.model_name !== "string" || !config.model_name.trim()) return false;
  const base = config.base_url || model.endpoint;
  if (typeof base !== "string" || !/^https?:\/\//i.test(base.trim())) return false;
  try {
    const endpoint = new URL(base.trim());
    return ["http:", "https:"].includes(endpoint.protocol) && Boolean(endpoint.hostname)
      && !endpoint.username && !endpoint.password && !endpoint.search && !endpoint.hash;
  } catch {
    return false;
  }
}
