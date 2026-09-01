import assert from "node:assert/strict";
import test from "node:test";
import {
  ALLOWED_DOCUMENT_EXTENSIONS,
  DEFAULT_MAX_UPLOAD_BYTES,
  buildFriendlyCron,
  formatFileSize,
  validateFileDescriptor,
  validateFiveFieldCron
} from "../src/lib/knowledgeImport.ts";

test("accepts every specified document extension", () => {
  for (const extension of ALLOWED_DOCUMENT_EXTENSIONS) {
    assert.equal(validateFileDescriptor({ name: `policy.${extension}`, size: 1024 }).ok, true);
  }
});

test("rejects unsupported, empty, and oversized files", () => {
  assert.equal(validateFileDescriptor({ name: "legacy.doc", size: 1024 }).reason, "不支援的格式");
  assert.equal(validateFileDescriptor({ name: "current.docx", size: 1024 }).ok, true);
  assert.equal(validateFileDescriptor({ name: "sheet.xlsx", size: 1024 }).reason, "不支援的格式");
  assert.equal(validateFileDescriptor({ name: "empty.pdf", size: 0 }).reason, "檔案內容為空");
  assert.equal(validateFileDescriptor({ name: "large.pdf", size: DEFAULT_MAX_UPLOAD_BYTES + 1 }).reason, "超過 100 MB 上限");
  assert.equal(validateFileDescriptor({ name: "limit.pdf", size: DEFAULT_MAX_UPLOAD_BYTES }).ok, true);
});

test("validates standard five-field cron ranges", () => {
  assert.equal(validateFiveFieldCron("0 2 * * *"), true);
  assert.equal(validateFiveFieldCron("*/15 8-18 * * 1-5"), true);
  assert.equal(validateFiveFieldCron("0,30 8 * * *"), true);
  assert.equal(validateFiveFieldCron("30 23 * * 1"), true);
  assert.equal(validateFiveFieldCron("0 24 * * *"), false);
  assert.equal(validateFiveFieldCron("60 2 * * *"), false);
  assert.equal(validateFiveFieldCron("0 2 * *"), false);
});

test("builds daily and weekly friendly schedules", () => {
  assert.equal(buildFriendlyCron("daily", 2, 0), "0 2 * * *");
  assert.equal(buildFriendlyCron("weekly", 9, 30, 1), "30 9 * * 1");
  assert.equal(buildFriendlyCron("minutes", 0, 0, 1, 15), "*/15 * * * *");
  assert.equal(buildFriendlyCron("hourly", 0, 10, 1, 2), "10 */2 * * *");
  assert.equal(buildFriendlyCron("daily", 24, 0), null);
});

test("formats upload file sizes for compact file rows", () => {
  assert.equal(formatFileSize(800), "800 B");
  assert.equal(formatFileSize(1536), "1.5 KB");
  assert.equal(formatFileSize(2 * 1024 * 1024), "2.0 MB");
});
