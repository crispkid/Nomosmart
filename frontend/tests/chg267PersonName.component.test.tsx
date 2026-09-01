import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { formatPersonName, personNameSearchText } from "@/lib/personName";
import type { Locale } from "@/lib/i18n";

function PersonNameProbe({ locale }: { locale: Locale }) {
  return <button aria-label={`Open ${formatPersonName({ given_name: "Peter", family_name: "Chu" }, locale)}`}>
    {formatPersonName({ given_name: "Peter", family_name: "Chu" }, locale)}
  </button>;
}

describe("CHG-267 localized person names", () => {
  const person = { given_name: "Jam", family_name: "Liu", display_name: "Jam Liu Liu" };

  it("renders family name first in Traditional Chinese without duplication", () => {
    expect(formatPersonName(person, "zh")).toBe("Liu Jam");
  });

  it("renders given name first in English without duplication", () => {
    expect(formatPersonName(person, "en")).toBe("Jam Liu");
  });

  it("falls back to one structured field and then the legacy display name", () => {
    expect(formatPersonName({ given_name: "Peter", family_name: null, display_name: "ignored" }, "zh")).toBe("Peter");
    expect(formatPersonName({ given_name: null, family_name: "Chu", display_name: "ignored" }, "en")).toBe("Chu");
    expect(formatPersonName({ given_name: null, family_name: null, display_name: "Legacy User" }, "zh")).toBe("Legacy User");
  });

  it("indexes both locale orderings and the legacy display value", () => {
    const search = personNameSearchText(person);
    expect(search).toContain("jam liu");
    expect(search).toContain("liu jam");
    expect(search).toContain("jam liu liu");
  });

  it("reorders mounted visible and accessible names immediately on locale change", () => {
    const view = render(<PersonNameProbe locale="zh" />);
    expect(screen.getByRole("button", { name: "Open Chu Peter" })).toHaveTextContent("Chu Peter");
    view.rerender(<PersonNameProbe locale="en" />);
    expect(screen.getByRole("button", { name: "Open Peter Chu" })).toHaveTextContent("Peter Chu");
  });
});
