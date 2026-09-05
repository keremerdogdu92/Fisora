const { spawn, spawnSync } = require("node:child_process");

const BASE_URL = "http://127.0.0.1:3000";
const isWindows = process.platform === "win32";
const npmCmd = isWindows ? "npm.cmd" : "npm";
const playwrightCli = require.resolve("@playwright/test/cli");

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function isServerReady() {
  try {
    const response = await fetch(BASE_URL, { cache: "no-store" });
    return response.ok;
  } catch {
    return false;
  }
}

async function waitForServer(timeoutMs = 120_000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (await isServerReady()) return;
    await sleep(500);
  }
  throw new Error(`Timed out waiting for ${BASE_URL}`);
}

function stopProcessTree(child) {
  if (!child?.pid) return;
  if (isWindows) {
    const killer = spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], {
      detached: true,
      stdio: "ignore",
    });
    killer.unref();
    return;
  }
  child.kill("SIGINT");
}

function runPlaywright(extraArgs) {
  return new Promise((resolve) => {
    const result = spawnSync(process.execPath, [playwrightCli, "test", ...extraArgs], {
      encoding: "utf8",
      env: { ...process.env, FISORA_PLAYWRIGHT_NO_WEBSERVER: "1" },
      timeout: Number(process.env.FISORA_PLAYWRIGHT_TIMEOUT_MS || 120_000),
    });
    const output = `${result.stdout || ""}${result.stderr || ""}`;
    const cleanOutput = output.replace(/\x1B\[[0-?]*[ -/]*[@-~]/g, "");
    process.stdout.write(result.stdout || "");
    process.stderr.write(result.stderr || "");

    if (typeof result.status === "number") {
      resolve(result.status);
      return;
    }
    if (/\d+\s+failed/.test(cleanOutput)) {
      resolve(1);
      return;
    }
    if (/\d+\s+passed/.test(cleanOutput) || /passed\s+\(/.test(cleanOutput)) {
      resolve(0);
      return;
    }
    if (result.error) console.error(result.error);
    resolve(1);
  });
}

(async () => {
  let devServer = null;
  const hadServer = await isServerReady();

  if (!hadServer) {
    devServer = spawn(`${npmCmd} run dev -- --hostname 127.0.0.1 --port 3000`, {
      detached: true,
      shell: isWindows,
      stdio: "ignore",
    });
    devServer.unref();
    await waitForServer();
  }

  try {
    const code = await runPlaywright(process.argv.slice(2));
    process.exitCode = code;
  } finally {
    if (devServer) stopProcessTree(devServer);
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
