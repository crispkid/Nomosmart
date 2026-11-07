export class IntegrationClientDateError extends Error {
  readonly reason: "invalid" | "ambiguous" | "unavailable";
  constructor(reason: IntegrationClientDateError["reason"]) {
    super("Integration client date could not be confirmed");
    this.reason = reason;
  }
}

const pad = (value: number) => String(value).padStart(2, "0");
function localMinute(date: Date): string {
  return `${String(date.getFullYear()).padStart(4, "0")}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Null is a missing date; a null return is an unreadable original timestamp. */
export function integrationClientDateInput(value: string | null): string | null {
  if (value === null) return "";
  if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return null;
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? localMinute(date) : null;
}

export function integrationClientDateValue(input: string): string | null {
  const value = input.trim();
  if (!value) return null;
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) throw new IntegrationClientDateError("invalid");
  const date = new Date(value);
  // The native parser rolls DST gaps and out-of-range calendar values forward.
  if (!Number.isFinite(date.getTime()) || localMinute(date) !== value) throw new IntegrationClientDateError("invalid");
  const offsets = new Set([date.getTimezoneOffset(), new Date(date.getTime() - 86400000).getTimezoneOffset(), new Date(date.getTime() + 86400000).getTimezoneOffset()]);
  for (const offset of offsets) {
    const alternative = new Date(date.getTime() + (offset - date.getTimezoneOffset()) * 60000);
    if (alternative.getTime() !== date.getTime() && localMinute(alternative) === value) throw new IntegrationClientDateError("ambiguous");
  }
  return date.toISOString();
}

/** Undefined means no write, retaining the original UTC and full DB precision. */
export function integrationClientDateUpdate(input: string, original: string | null): string | null | undefined {
  const baseline = integrationClientDateInput(original);
  if (baseline === null) throw new IntegrationClientDateError("unavailable");
  if (input.trim() === baseline) return undefined;
  return integrationClientDateValue(input);
}
