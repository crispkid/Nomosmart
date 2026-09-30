/**
 * Reviewed exact literals that are not natural-language UI copy.
 *
 * @typedef {{
 *   externalBrand: readonly string[],
 *   protocol: readonly string[],
 *   stableField: readonly string[],
 *   technicalId: readonly string[]
 * }} VisibleTextAllowlist
 */

/** @type {VisibleTextAllowlist} */
export const visibleTextAllowlist = Object.freeze({
  externalBrand: Object.freeze(["Keycloak OIDC", "NomoSmart"]),
  protocol: Object.freeze([
    "API",
    "CSV",
    "DOCX",
    "FTP",
    "FTPS",
    "HTTP",
    "HTTP API",
    "LLM",
    "JSON",
    "MD",
    "MB",
    "OIDC",
    "OCR",
    "PDF",
    "PDF · DOCX · TXT · MD",
    "S3",
    "SFTP",
    "TLS",
    "TXT"
  ]),
  stableField: Object.freeze([
    "UUID",
    "Anthropic-Version",
    "chat_test",
    "chunk_auto_tag",
    "connection_test",
    "document_auto_tag",
    "embedding_build",
    "knowledge_detail",
    "ocr_extract",
    "pipeline",
    "public_api",
    "public_api_chat",
    "query_embedding",
    "system_management",
    "validation",
    "validation_answer",
    "validation_judge"
  ]),
  technicalId: Object.freeze([
    ".csv · UTF-8",
    "America/New_York",
    "Asia/Taipei",
    "Asia/Tokyo",
    "Europe/London",
    "N",
    "Embedding",
    "Explicit TLS",
    "Implicit TLS",
    "Judge",
    "claude-3-5-sonnet-latest",
    "files.example.com",
    "gemini-1.5-pro",
    "https://s3.example.com",
    "llama3.1",
    "ms",
    "Q",
    "ap-northeast-1",
    "http://127.0.0.1:8000/v1",
    "https://api.anthropic.com",
    "https://api.example.com/document.json",
    "knowledge-source",
    "policies/2026",
    "policy.pdf",
    "question, expected_answer, expected_keywords, selected_document_ids, category, priority",
    "question、expected_answer、expected_keywords、selected_document_ids、category、priority",
    "{\"Accept\":\"application/json\"}"
  ])
});
