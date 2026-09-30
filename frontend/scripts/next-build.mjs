import { readFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const frontendDir = fileURLToPath(new URL("..", import.meta.url));
const devLockPath = fileURLToPath(new URL("../.next-dev/dev/lock", import.meta.url));
const nextCliPath = fileURLToPath(new URL("../node_modules/next/dist/bin/next", import.meta.url));

async function devServerStatus() {
  let lock;
  try {
    lock = JSON.parse(await readFile(devLockPath, "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") return "stopped";
    return "unknown";
  }

  if (!Number.isInteger(lock?.pid) || lock.pid <= 0) return "unknown";
  try {
    process.kill(lock.pid, 0);
    return "running";
  } catch (error) {
    return error?.code === "ESRCH" ? "stopped" : "running";
  }
}

const status = await devServerStatus();
if (status !== "stopped") {
  console.error(
    status === "running"
      ? "Production build refused: stop the running Next.js development server first."
      : "Production build refused: the Next.js development lock cannot be verified safely."
  );
  process.exitCode = 2;
} else {
  const child = spawn(process.execPath, [nextCliPath, "build", ...process.argv.slice(2)], {
    cwd: frontendDir,
    env: process.env,
    stdio: "inherit"
  });

  child.on("error", (error) => {
    console.error(`Unable to start Next.js production build: ${error.message}`);
    process.exitCode = 1;
  });
  child.on("close", (code, signal) => {
    if (signal) console.error(`Next.js production build stopped by ${signal}.`);
    process.exitCode = code ?? 1;
  });
}
