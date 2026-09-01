import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AIModelCredentialClearControl, OpenAiApiModeField } from "@/components/AIModelCompatibilityFields";
import { setLocalePreference } from "@/lib/i18nClient";


describe("CHG-268 model compatibility fields", () => {
  it("defaults new OpenAI Chat models to Responses and existing absent-mode models to legacy", () => {
    setLocalePreference("en", false);
    const view = render(<OpenAiApiModeField isExisting={false} modelType="Chat" />);
    expect(screen.getByRole("combobox", { name: /OpenAI API mode/i })).toHaveValue("responses");
    view.rerender(<OpenAiApiModeField isExisting modelType="Judge" />);
    expect(screen.getByRole("combobox", { name: /OpenAI API mode/i })).toHaveValue("chat_completions");
    view.rerender(<OpenAiApiModeField existingMode="responses" isExisting modelType="Judge" />);
    expect(screen.getByRole("combobox", { name: /OpenAI API mode/i })).toHaveValue("responses");
    setLocalePreference("zh", false);
  });

  it("requires an explicit clear selection before showing model-name confirmation", async () => {
    setLocalePreference("en", false);
    const user = userEvent.setup();
    let clearDraft = false;
    let confirmation = "";
    const renderControl = () => <AIModelCredentialClearControl clearDraft={clearDraft} configured confirmation={confirmation} modelName="nomosmart-ocr" onClearChange={(checked) => { clearDraft = checked; view.rerender(renderControl()); }} onConfirmationChange={(value) => { confirmation = value; view.rerender(renderControl()); }} />;
    const view = render(renderControl());
    expect(screen.queryByPlaceholderText("nomosmart-ocr")).not.toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: /Explicitly clear/i }));
    const confirmationInput = screen.getByPlaceholderText("nomosmart-ocr");
    await user.type(confirmationInput, "nomosmart-ocr");
    expect(confirmationInput).toHaveValue("nomosmart-ocr");
    setLocalePreference("zh", false);
  });
});
