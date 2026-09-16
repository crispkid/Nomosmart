import { existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { createRunManifestPath, runWithCleanup } from "./e2eRunLifecycle.mjs";

const reportPath = fileURLToPath(new URL("../../test-results/e2e/summary.json", import.meta.url));
const backendRoot = fileURLToPath(new URL("../../backend/", import.meta.url));
const fixtureScript = fileURLToPath(new URL("../../backend/scripts/e2e_governance_fixture.py", import.meta.url));
const defaultPython = fileURLToPath(new URL("../../backend/.venv/bin/python", import.meta.url));
const macChromePath = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const checks = [];
const execFileAsync = promisify(execFile);
let runManifest;

function requiredEnv(name) {
  const value = process.env[name];
  if (!value || value.trim() === "") {
    return null;
  }
  return value.replace(/\/$/, "");
}

async function record(name, fn) {
  const startedAt = Date.now();
  try {
    await fn();
    checks.push({ name, status: "passed", duration_ms: Date.now() - startedAt });
  } catch (error) {
    checks.push({
      name,
      status: error?.code === "E2E_BLOCKED" ? "blocked" : "failed",
      duration_ms: Date.now() - startedAt,
      error: error instanceof Error ? error.message : String(error),
      ...(error?.primaryCode ? { primary_code: error.primaryCode } : {}),
      ...(error?.cleanupErrors ? { cleanup_errors: error.cleanupErrors, manifest: runManifest } : {})
    });
  }
}

function blocked(message) {
  const error = new Error(message);
  error.code = "E2E_BLOCKED";
  throw error;
}

async function expectReachable(name, url) {
  const response = await fetch(url, { redirect: "manual" });
  if (response.status >= 500) {
    throw new Error(`${name} returned HTTP ${response.status}`);
  }
}

const frontendBaseUrl = requiredEnv("E2E_FRONTEND_BASE_URL");
const backendBaseUrl = requiredEnv("E2E_BACKEND_BASE_URL");
const oidcIssuerUrl = requiredEnv("E2E_OIDC_ISSUER_URL");
const peterEmail = requiredEnv("E2E_PETER_EMAIL");
const peterPassword = process.env.E2E_PETER_PASSWORD || "";
const johnEmail = requiredEnv("E2E_JOHN_EMAIL");
const johnPassword = process.env.E2E_JOHN_PASSWORD || "";

await record("live E2E prerequisites are configured", async () => {
  const missing = [
    ["E2E_FRONTEND_BASE_URL", frontendBaseUrl],
    ["E2E_BACKEND_BASE_URL", backendBaseUrl],
    ["E2E_OIDC_ISSUER_URL", oidcIssuerUrl],
    ["E2E_PETER_EMAIL", peterEmail],
    ["E2E_PETER_PASSWORD", peterPassword],
    ["E2E_JOHN_EMAIL", johnEmail],
    ["E2E_JOHN_PASSWORD", johnPassword]
  ].filter(([, value]) => !value).map(([name]) => name);
  if (missing.length > 0) {
    blocked(`Missing required live E2E environment variables: ${missing.join(", ")}`);
  }
});

if (frontendBaseUrl && backendBaseUrl && oidcIssuerUrl) {
  await record("frontend live endpoint is reachable", async () => {
    await expectReachable("frontend", frontendBaseUrl);
  });

  await record("backend live health endpoint is reachable", async () => {
    await expectReachable("backend", `${backendBaseUrl}/health`);
  });

  await record("OIDC issuer discovery endpoint is reachable", async () => {
    await expectReachable("OIDC issuer", `${oidcIssuerUrl}/.well-known/openid-configuration`);
  });

  await record("browser-backed E2E runner is available", async () => {
    try {
      await import("@playwright/test");
    } catch {
      blocked("@playwright/test is required for browser-backed TEST-002 E2E acceptance");
    }
    const executablePath = browserExecutablePath();
    if (executablePath) return;
  });
}

if (frontendBaseUrl && backendBaseUrl && oidcIssuerUrl && peterEmail && peterPassword && johnEmail && johnPassword) {
  await record("browser-backed peter/john governance and publish acceptance passes", async () => {
    runManifest = await createRunManifestPath();
    let browser;
    await runWithCleanup({
      setup: async () => {
        await fixtureCommand("init");
        return fixtureCommand("setup", "--peter-email", peterEmail, "--john-email", johnEmail);
      },
      execute: async (fixture) => {
      const { chromium } = await import("@playwright/test");
      browser = await chromium.launch(browserLaunchOptions());
      const johnContext = await browser.newContext();
      const johnPage = await johnContext.newPage();
      await loginAs(johnPage, johnEmail, johnPassword);
      await expectBodyText(johnPage, /首頁|Home/, "home");
      await navigateViaLink(johnPage, "/approve");
      await expectBodyText(johnPage, /簽核工作台|Approval/, "approval workspace");
      await navigateViaLink(johnPage, "/projects");
      await expectBodyText(johnPage, /知識專案|Knowledge Project/, "projects");
      await navigateViaLink(johnPage, fixture.project_path);
      const johnProjectBody = await bodyText(johnPage);
      if (/權限管理|Permission Management/.test(johnProjectBody)) {
        throw new Error("Non-owner John can still see the project Permission Management entry");
      }
      if (await johnPage.locator('a[href="/system"]').count()) throw new Error("John can see the System Management navigation entry");
      await navigateViaLink(johnPage, fixture.knowledge_path);
      const deleteChunkButton = johnPage.getByRole("button", { name: /刪除第 .* 個切片|Delete chunk/i }).first();
      await deleteChunkButton.waitFor({ state: "visible", timeout: 30_000 });
      await deleteChunkButton.click();
      await expectBodyText(johnPage, /永久刪除此切片|Permanently delete this chunk/i, "chunk deletion confirmation");
      const cancelChunkDeletion = johnPage.getByRole("button", { name: /^(取消|Cancel)$/ }).first();
      await cancelChunkDeletion.click();
      if (await johnPage.getByRole("alertdialog").count()) throw new Error("Chunk deletion confirmation did not close after cancellation");
      await navigateViaLink(johnPage, `${fixture.knowledge_path}/chat-test`);
      await navigateViaLink(johnPage, fixture.submit_path);
      const submitButton = johnPage.getByRole("button", { name: /^(送出|Submit)$/ }).first();
      await submitButton.waitFor({ state: "visible", timeout: 30_000 });
      await submitButton.click({ timeout: 30_000 }).catch(async (error) => {
        throw new Error(`John's editor role cannot submit the fixture for review: ${(await bodyText(johnPage)).slice(0, 800)}`, { cause: error });
      });
      await expectBodyText(johnPage, /已送至下一關|Sent to the Next Stage/, "successful review submission");
      await johnContext.close();

      const peterContext = await browser.newContext();
      const peterPage = await peterContext.newPage();
      await loginAs(peterPage, peterEmail, peterPassword);
      await expectBodyText(peterPage, /首頁|Home/, "home");
      await navigateViaLink(peterPage, "/system");
      await expectBodyText(peterPage, /系統管理|System Management/, "system management");
      await navigateViaLink(peterPage, "/projects");
      await navigateViaLink(peterPage, fixture.project_path);
      await expectBodyText(peterPage, /權限管理|Permission Management/, "owner permission management entry");

      const managerTask = await pendingTask(fixture.project_id, "manager_review");
      await approveTask(peterPage, managerTask.id);
      const ownerTask = await pendingTask(fixture.project_id, "owner_review");
      await approveTask(peterPage, ownerTask.id);

      await peterPage.waitForURL((url) => url.pathname === "/approve", { timeout: 10_000 });
      const publishRow = peterPage.locator(".approval-pending-publish-row").filter({ hasText: fixture.document_title }).first();
      const publishButton = publishRow.getByRole("button", { name: /^(發布|Publish)$/ }).first();
      await publishButton.waitFor({ state: "visible", timeout: 30_000 });
      await publishButton.click();
      await expectBodyText(peterPage, /發布.*代|Published.*generation/i, "successful live publication");
      await peterContext.close();

      const evidence = await fixtureCommand("inspect", "--project-id", fixture.project_id);
      if (evidence.version_status !== "active" || !evidence.published_at) {
        throw new Error(`Published fixture has invalid version state: ${JSON.stringify(evidence)}`);
      }
      if (evidence.graph_job_status !== "completed" || Number(evidence.neo4j_nodes) < 3) {
        throw new Error(`Live Neo4j publication evidence is incomplete: ${JSON.stringify(evidence)}`);
      }
      if (Number(evidence.opensearch_documents) < 1) {
        throw new Error(`Live OpenSearch publication evidence is incomplete: ${JSON.stringify(evidence)}`);
      }
      },
      close: async () => { if (browser) await browser.close(); },
      cleanup: async () => {
        if (existsSync(runManifest)) await fixtureCommand("cleanup");
      }
    });
  });
}

async function fixtureCommand(...args) {
  const python = process.env.E2E_PYTHON || defaultPython;
  let stdout;
  let failed = false;
  try {
    ({ stdout } = await execFileAsync(python, [fixtureScript, ...args, "--manifest", runManifest], {
      cwd: backendRoot, env: process.env, timeout: 120_000, killSignal: "SIGKILL", maxBuffer: 1024 * 1024
    }));
  } catch (error) {
    stdout = error.stdout || ""; failed = true;
  }
  const line = stdout.trim().split("\n").at(-1);
  if (!line) throw new Error(`Fixture command returned no output: ${args[0]}`);
  let result;
  try { result = JSON.parse(line); }
  catch { throw new Error("E2E helper returned invalid evidence"); }
  if (failed || result.status === "failed" || result.status === "blocked") {
    const error = new Error(result.code === "E2E_BLOCKED"
      ? "Genuine generation and run-owned workflow receipts are required"
      : "E2E helper failed; inspect the private run receipt");
    error.code = result.code || "E2E_HELPER_FAILURE";
    throw error;
  }
  return result;
}

async function pendingTask(projectId, stage) {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const evidence = await fixtureCommand("inspect", "--project-id", projectId);
    const task = evidence.tasks.find((item) => item.review_stage === stage && item.status === "pending");
    if (task) return task;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Pending ${stage} task was not created for project ${projectId}`);
}

async function approveTask(page, taskId) {
  await navigateViaLink(page, "/approve");
  await navigateViaLink(page, `/approve/${taskId}`);
  const approve = page.getByRole("button", { name: /^(核准|Approve)$/ }).first();
  await approve.waitFor({ state: "visible", timeout: 30_000 });
  await approve.click();
  const confirm = page.getByRole("button", { name: /^(確認核准|Confirm approval)$/ }).first();
  await confirm.waitFor({ state: "visible", timeout: 10_000 });
  await confirm.click();
  await expectBodyText(page, /已核准|Approved|已送交|submitted/i, `approval task ${taskId}`);
}

async function navigateViaLink(page, href) {
  const link = page.locator(`a[href="${href}"]`).first();
  await link.waitFor({ state: "visible", timeout: 30_000 });
  await link.click();
  await page.waitForURL((url) => url.pathname === href.split("?")[0], { timeout: 30_000 });
  await waitForAuthSettled(page);
}

function browserLaunchOptions() {
  const executablePath = browserExecutablePath();
  return {
    headless: process.env.E2E_HEADLESS !== "0",
    ...(executablePath ? { executablePath } : {})
  };
}

function browserExecutablePath() {
  if (process.env.E2E_BROWSER_EXECUTABLE_PATH) return process.env.E2E_BROWSER_EXECUTABLE_PATH;
  if (existsSync(macChromePath)) return macChromePath;
  return null;
}

async function loginAs(page, email, password) {
  await page.goto(new URL("/login", frontendBaseUrl).href, { waitUntil: "domcontentloaded" });
  const loginLink = page.locator('a[href*="/api/auth/start"], a:has-text("Keycloak"), a:has-text("登入"), a:has-text("Login"), a:has-text("Sign in")').first();
  if (await loginLink.isVisible({ timeout: 10_000 }).catch(() => false)) {
    await loginLink.click();
  } else {
    await page.goto(new URL("/api/auth/start", frontendBaseUrl).href, { waitUntil: "domcontentloaded" });
  }
  await page.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => undefined);
  const username = page.locator('input[name="username"], input#username, input[name="email"], input[type="email"], input[type="text"]').first();
  await username.waitFor({ state: "visible", timeout: 30_000 });
  await username.fill(email);
  const passwordInput = page.locator('input[type="password"], input[name="password"], input#password').first();
  if (!(await passwordInput.isVisible({ timeout: 2_000 }).catch(() => false))) {
    await clickSubmit(page);
  }
  await passwordInput.waitFor({ state: "visible", timeout: 30_000 });
  await passwordInput.fill(password);
  await clickSubmit(page);
  await page.waitForURL((url) => (
    url.origin === new URL(frontendBaseUrl).origin
    && !url.pathname.startsWith("/api/auth/")
    && !url.pathname.includes("/login")
    && !url.pathname.includes("/auth/callback")
  ), { timeout: 60_000 });
  await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => undefined);
  await waitForAuthSettled(page);
  const text = await bodyText(page);
  if (/login|登入|sign in|username|password/i.test(text) && !/首頁|Home|NomoSmart/.test(text)) {
    throw new Error(`Login did not reach an authenticated app page for ${email}`);
  }
}

async function clickSubmit(page) {
  const submit = page.locator('button[type="submit"], input[type="submit"], button:has-text("登入"), button:has-text("Login"), button:has-text("Log in"), button:has-text("Sign in"), button:has-text("Continue"), button:has-text("下一步")').first();
  await submit.waitFor({ state: "visible", timeout: 15_000 });
  await submit.click();
}

async function expectPageContains(page, path, pattern) {
  await page.goto(new URL(path, frontendBaseUrl).href, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => undefined);
  await expectBodyText(page, pattern, path);
}

async function expectBodyText(page, pattern, label) {
  await page.waitForFunction(
    ([source, flags]) => new RegExp(source, flags).test(document.body?.innerText || ""),
    [pattern.source, pattern.flags],
    { timeout: 30_000 }
  ).catch(() => undefined);
  const text = await bodyText(page);
  if (!pattern.test(text)) {
    throw new Error(`Expected ${label} to contain ${pattern}, got: ${text.slice(0, 400)}`);
  }
}

async function bodyText(page) {
  await waitForAuthSettled(page);
  return (await page.locator("body").innerText({ timeout: 15_000 })).replace(/\s+/g, " ").trim();
}

async function waitForAuthSettled(page) {
  await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      const path = window.location.pathname;
      return !path.startsWith("/api/auth/")
        && path !== "/auth/callback"
        && !/正在確認企業登入狀態|Checking enterprise sign-in|Checking session|正在完成企業登入|Completing enterprise sign-in/i.test(text);
    },
    undefined,
    { timeout: 60_000 }
  );
}

const failed = checks.filter((check) => check.status === "failed");
const blockedChecks = checks.filter((check) => check.status === "blocked");
const report = {
  generated_at: new Date().toISOString(),
  mode: "live-e2e-browser-acceptance",
  summary: {
    total: checks.length,
    passed: checks.filter((check) => check.status === "passed").length,
    failed: failed.length,
    skipped: 0,
    blocked: blockedChecks.length
  },
  checks
};

await mkdir(dirname(reportPath), { recursive: true });
await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`);

for (const check of checks) {
  const marker = check.status === "passed" ? "ok" : "not ok";
  console.log(`${marker}: ${check.name} [${check.status}]`);
  if (check.error) console.log(`  ${check.error}`);
}
console.log(`live E2E report written to ${reportPath}`);

if (failed.length > 0 || blockedChecks.length > 0) process.exit(1);
