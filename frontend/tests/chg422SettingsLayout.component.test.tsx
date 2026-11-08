import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { page } from "vitest/browser";
import { SettingsCard, SettingsFieldRow } from "@/components/SettingsCard";
import { t } from "@/lib/i18n";
import "@/app/globals.css";

// Native component geometry only. No server configuration, auth or save success is supplied.
describe("CHG-422 settings component geometry", () => {
  for (const locale of ["zh", "en"] as const) for (const width of [1440, 1024, 768, 767, 390, 320]) {
    it(`keeps distinct headers and independent rows readable at ${width}px (${locale})`, async () => {
      await page.viewport(width, 1000);
      const result = render(<div className="system-workspace"><div className="settings-main">
        <SettingsCard panel="native-layout-upload" title={t("settingsUpload", locale)}>
          <SettingsFieldRow htmlFor="native-upload" label={t("systemUploadLimitLabel", locale)} help={t("settingsUploadHelp", locale)}>
            <input id="native-upload" type="number" aria-describedby="native-upload-help" />
          </SettingsFieldRow>
          <SettingsFieldRow htmlFor="native-retention" label={t("systemStagingTtlLabel", locale)} help={t("settingsRetentionHelp", locale)}>
            <input id="native-retention" type="number" aria-describedby="native-retention-help" />
          </SettingsFieldRow>
        </SettingsCard>
        <SettingsCard panel="native-layout-ocr" title={t("settingsOCR", locale)}>
          <p>{t("ocrRequestTokenSettingHelp", locale)}</p>
        </SettingsCard>
      </div></div>);
      const first = screen.getByLabelText(t("systemUploadLimitLabel", locale));
      const second = screen.getByLabelText(t("systemStagingTtlLabel", locale));
      expect(second.getBoundingClientRect().top).toBeGreaterThan(first.getBoundingClientRect().bottom);
      const cards = [...result.container.querySelectorAll<HTMLElement>(".settings-card")];
      expect(cards[1].getBoundingClientRect().top).toBeGreaterThanOrEqual(cards[0].getBoundingClientRect().bottom);
      const header = cards[0].querySelector<HTMLElement>(".system-section-header")!;
      const body = cards[0].querySelector<HTMLElement>(".settings-card-content")!;
      expect(getComputedStyle(header).backgroundColor).not.toBe(getComputedStyle(cards[0]).backgroundColor);
      expect(body.getBoundingClientRect().top).toBeGreaterThanOrEqual(header.getBoundingClientRect().bottom);
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
      expect(first.getBoundingClientRect().height).toBeGreaterThanOrEqual(40);
      expect(first.getBoundingClientRect().right).toBeLessThanOrEqual(width);
      result.unmount();
    });
  }
  it("uses the same 28px offset for sibling child fields", async () => {
    await page.viewport(1024, 900);
    const result = render(<div className="settings-main"><section className="identity-settings-section">
      <div className="identity-form-grid"><label data-native-level="parent">{t("protocolDailySync", "en")}<input type="checkbox" /></label>
        <label className="settings-child-field" data-native-level="child">{t("protocolDailyTime", "en")}<input type="time" /></label>
        <div className="settings-child-field"><label data-native-level="child">{t("protocolTimezone", "en")}<input type="text" /></label></div>
      </div>
    </section></div>);
    const parent = result.container.querySelector<HTMLElement>('[data-native-level="parent"]')!;
    const children = [...result.container.querySelectorAll<HTMLElement>('[data-native-level="child"]')];
    for (const child of children) expect(Math.round(child.querySelector("input")!.getBoundingClientRect().left - parent.getBoundingClientRect().left)).toBe(28);
    result.unmount();
  });
});
