document.addEventListener("DOMContentLoaded", () => {
  const submittingLabel = document.body.dataset.submittingLabel || "";

  document.querySelectorAll(".nomosmart-auth-workspace form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (form.dataset.submitting === "true") {
        event.preventDefault();
        return;
      }

      form.dataset.submitting = "true";
      form.setAttribute("aria-busy", "true");

      window.setTimeout(() => {
        form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach((control) => {
          control.disabled = true;
          control.dataset.nomosmartSubmitting = "true";
          if (submittingLabel && control instanceof HTMLButtonElement) {
            control.textContent = submittingLabel;
          }
        });
      }, 0);
    });
  });
});
