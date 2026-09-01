export const DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
export const ALLOWED_DOCUMENT_EXTENSIONS = ["pdf", "docx", "txt", "md", "markdown", "csv", "json"] as const;
export const UPLOAD_REASON_UNSUPPORTED = "不支援的格式";
export const UPLOAD_REASON_TOO_LARGE = "超過 100 MB 上限";
export const UPLOAD_REASON_EMPTY = "檔案內容為空";
export const UPLOAD_REASON_READY = "可上傳";

export type FileDescriptor = { name: string; size: number };
export type FileValidationResult = { name: string; ok: boolean; reason: string };

export function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function documentExtension(name: string) {
  return name.toLowerCase().split(".").pop() ?? "";
}

export function validateFileDescriptor(file: FileDescriptor, maxBytes = DEFAULT_MAX_UPLOAD_BYTES): FileValidationResult {
  if (!ALLOWED_DOCUMENT_EXTENSIONS.includes(documentExtension(file.name) as (typeof ALLOWED_DOCUMENT_EXTENSIONS)[number])) {
    return { name: file.name, ok: false, reason: UPLOAD_REASON_UNSUPPORTED };
  }
  if (file.size > maxBytes) return { name: file.name, ok: false, reason: UPLOAD_REASON_TOO_LARGE };
  if (file.size === 0) return { name: file.name, ok: false, reason: UPLOAD_REASON_EMPTY };
  return { name: file.name, ok: true, reason: UPLOAD_REASON_READY };
}

function validCronValue(value: string, min: number, max: number) {
  if (!/^\d+$/.test(value)) return false;
  const numeric = Number(value);
  return numeric >= min && numeric <= max;
}

function validCronField(field: string, min: number, max: number) {
  return field.split(",").every((part) => {
    const [base, step] = part.split("/");
    if (step !== undefined && (!/^\d+$/.test(step) || Number(step) < 1)) return false;
    if (base === "*") return true;
    const range = base.split("-");
    if (range.length === 1) return validCronValue(range[0], min, max);
    return range.length === 2 && validCronValue(range[0], min, max) && validCronValue(range[1], min, max) && Number(range[0]) <= Number(range[1]);
  });
}

export function validateFiveFieldCron(expression: string) {
  const fields = expression.trim().split(/\s+/);
  if (fields.length !== 5) return false;
  return validCronField(fields[0], 0, 59)
    && validCronField(fields[1], 0, 23)
    && validCronField(fields[2], 1, 31)
    && validCronField(fields[3], 1, 12)
    && validCronField(fields[4], 0, 7);
}

export function buildFriendlyCron(frequency: "minutes" | "hourly" | "daily" | "weekly", hour: number, minute: number, weekday = 1, interval = 1) {
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59 || weekday < 0 || weekday > 7 || interval < 1) return null;
  if (frequency === "minutes") return `*/${Math.min(interval, 59)} * * * *`;
  if (frequency === "hourly") return `${minute} */${Math.min(interval, 23)} * * *`;
  return frequency === "weekly" ? `${minute} ${hour} * * ${weekday}` : `${minute} ${hour} * * *`;
}
