import { describe, expect, it } from "vitest";

import { aiModelProviderName, missingProviderModelName } from "@/components/AIModelInventoryFields";

describe("CHG-269 AI model inventory provider-model field", () => {
  it("returns the trimmed provider model identifier", () => {
    expect(aiModelProviderName({ model_name: "  gpt-5.6-luna  " })).toBe("gpt-5.6-luna");
    expect(aiModelProviderName({ model_name: "text-embedding-3-small" })).toBe("text-embedding-3-small");
  });

  it.each([
    undefined,
    null,
    {},
    { model_name: null },
    { model_name: 42 },
    { model_name: "   " },
  ])("uses an em dash for a missing or invalid provider model name", (config) => {
    expect(aiModelProviderName(config as Record<string, unknown> | null | undefined)).toBe(missingProviderModelName);
    expect(missingProviderModelName).toBe("—");
  });
});
