export const missingProviderModelName = "—";

export function aiModelProviderName(config: Record<string, unknown> | null | undefined) {
  const value = config?.model_name;
  if (typeof value !== "string") return missingProviderModelName;
  const normalized = value.trim();
  return normalized || missingProviderModelName;
}
