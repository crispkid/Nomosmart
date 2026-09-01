import { describe, expect, it } from "vitest";

import type { ApiError } from "@/lib/api";
import { formatTranslation, localizeKnownMessage, t, type Locale, type TranslationKey } from "@/lib/i18n";
import { operationalErrorMessage } from "@/lib/operationalMessages";

function translators(locale: Locale) {
  return {
    translate: (key: TranslationKey) => t(key, locale),
    format: (key: TranslationKey, params: Record<string, string | number>) => formatTranslation(key, params, locale),
  };
}

function apiError(code: string, status: number, requestId?: string) {
  return Object.assign(new Error("Backend prose must not be shown"), { code, status, requestId }) as ApiError;
}

describe("CHG-250 operational message localization", () => {
  it("maps a known project model code in both supported locales", () => {
    const zh = translators("zh");
    const en = translators("en");
    expect(operationalErrorMessage(apiError("project_model_configuration_required", 422), zh.translate, zh.format)).toBe(t("projectsModelConfigurationRequired", "zh"));
    expect(operationalErrorMessage(apiError("project_model_configuration_required", 422), en.translate, en.format)).toBe(t("projectsModelConfigurationRequired", "en"));
  });

  it("uses a localized safe fallback and retains the request ID for unknown codes", () => {
    const zh = translators("zh");
    const message = operationalErrorMessage(apiError("new_unknown_code", 418, "req-chg250"), zh.translate, zh.format);
    expect(message).toContain(t("apiGenericError", "zh"));
    expect(message).toContain("req-chg250");
    expect(message).not.toContain("Backend prose");
  });

  it("re-resolves an already mounted formatted message after locale changes", () => {
    const zhMessage = formatTranslation("apiErrorWithRequestId", { message: t("apiGenericError", "zh"), requestId: "req-switch" }, "zh");
    const enMessage = localizeKnownMessage(zhMessage, "en");
    expect(enMessage).toContain(t("apiGenericError", "en"));
    expect(enMessage).toContain("req-switch");
    expect(enMessage).not.toContain(t("apiGenericError", "zh"));
  });
});
