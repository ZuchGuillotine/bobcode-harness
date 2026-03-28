import fs from "fs";
import http from "http";
import path from "path";
import { chromium } from "playwright";

const stateFile = process.env.HARNESS_BROWSER_STATE_FILE;
const artifactsDir = process.env.HARNESS_BROWSER_ARTIFACTS_DIR;
const consoleLog = process.env.HARNESS_BROWSER_CONSOLE_LOG;
const networkLog = process.env.HARNESS_BROWSER_NETWORK_LOG;
const authToken = process.env.HARNESS_BROWSER_TOKEN;
const mode = process.env.HARNESS_BROWSER_MODE || "headless";
const version = process.env.HARNESS_BROWSER_VERSION || "v1";
const host = "127.0.0.1";
const allowRemote = process.env.HARNESS_BROWSER_ALLOW_REMOTE === "true";
const idleTimeoutMs = Number.parseInt(
  process.env.HARNESS_BROWSER_IDLE_TIMEOUT_MS || "1800000",
  10,
);

if (!stateFile || !artifactsDir || !consoleLog || !networkLog || !authToken) {
  process.stderr.write("Missing required browser daemon environment\n");
  process.exit(1);
}

fs.mkdirSync(path.dirname(stateFile), { recursive: true });
fs.mkdirSync(artifactsDir, { recursive: true });

let browser = null;
let context = null;
let activePageIndex = 0;
let refs = new Map();
let lastSeenAt = new Date().toISOString();
const startedAt = new Date().toISOString();
let idleTimer = null;
const consoleEntries = [];
const networkEntries = [];
const maxLogEntries = 200;
const wiredPages = new WeakSet();

function appendLog(filePath, line) {
  fs.appendFileSync(filePath, `${line}\n`);
}

function trimLog(entries) {
  while (entries.length > maxLogEntries) {
    entries.shift();
  }
}

function setIdleTimer() {
  if (idleTimer) {
    clearTimeout(idleTimer);
  }
  idleTimer = setTimeout(() => {
    shutdown(0).catch(() => {
      process.exit(0);
    });
  }, idleTimeoutMs);
}

function validateUrl(url) {
  if (url === "about:blank") return;
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error(`Invalid URL: ${url}`);
  }
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error(`Unsupported URL protocol: ${parsed.protocol}`);
  }
  if (allowRemote) return;
  const hostname = parsed.hostname.toLowerCase();
  const allowedHosts = new Set(["127.0.0.1", "localhost", "::1"]);
  if (!allowedHosts.has(hostname)) {
    throw new Error(`Remote navigation is disabled in v1: ${hostname}`);
  }
}

function getPages() {
  return context ? context.pages() : [];
}

function getActivePage() {
  const pages = getPages();
  if (pages.length === 0) {
    throw new Error("No browser page available");
  }
  if (activePageIndex >= pages.length) {
    activePageIndex = pages.length - 1;
  }
  return pages[activePageIndex];
}

function wirePage(page) {
  if (wiredPages.has(page)) {
    return;
  }
  wiredPages.add(page);

  page.on("console", (msg) => {
    const entry = {
      type: msg.type(),
      text: msg.text(),
      url: page.url(),
      ts: new Date().toISOString(),
    };
    consoleEntries.push(entry);
    trimLog(consoleEntries);
    appendLog(consoleLog, JSON.stringify(entry));
  });

  page.on("pageerror", (error) => {
    const entry = {
      type: "pageerror",
      text: error.message,
      url: page.url(),
      ts: new Date().toISOString(),
    };
    consoleEntries.push(entry);
    trimLog(consoleEntries);
    appendLog(consoleLog, JSON.stringify(entry));
  });

  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame()) {
      refs = new Map();
    }
  });

  page.on("dialog", async (dialog) => {
    const entry = {
      type: "dialog",
      text: dialog.message(),
      url: page.url(),
      ts: new Date().toISOString(),
    };
    consoleEntries.push(entry);
    trimLog(consoleEntries);
    appendLog(consoleLog, JSON.stringify(entry));
    await dialog.dismiss();
  });
}

function wireContext(ctx) {
  ctx.on("page", (page) => {
    wirePage(page);
  });

  ctx.on("requestfailed", (request) => {
    const entry = {
      kind: "requestfailed",
      method: request.method(),
      url: request.url(),
      failure: request.failure()?.errorText || "unknown",
      ts: new Date().toISOString(),
    };
    networkEntries.push(entry);
    trimLog(networkEntries);
    appendLog(networkLog, JSON.stringify(entry));
  });

  ctx.on("response", async (response) => {
    if (response.status() < 400) return;
    const entry = {
      kind: "response",
      method: response.request().method(),
      url: response.url(),
      status: response.status(),
      ts: new Date().toISOString(),
    };
    networkEntries.push(entry);
    trimLog(networkEntries);
    appendLog(networkLog, JSON.stringify(entry));
  });
}

async function launchBrowser() {
  browser = await chromium.launch({
    headless: mode !== "headed",
  });
  browser.on("disconnected", () => {
    process.exit(1);
  });
  context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  wireContext(context);
  const page = await context.newPage();
  activePageIndex = 0;
}

function writeState(port) {
  const payload = {
    pid: process.pid,
    port,
    token: authToken,
    started_at: startedAt,
    last_seen_at: lastSeenAt,
    mode,
    version,
  };
  const tmp = `${stateFile}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(payload, null, 2), { mode: 0o600 });
  fs.renameSync(tmp, stateFile);
}

function touchState(port) {
  lastSeenAt = new Date().toISOString();
  writeState(port);
  setIdleTimer();
}

function sendJson(res, statusCode, payload) {
  res.writeHead(statusCode, { "Content-Type": "application/json" });
  res.end(JSON.stringify(payload));
}

function isAuthorized(req) {
  return req.headers.authorization === `Bearer ${authToken}`;
}

async function buildSnapshot(page) {
  const selector = [
    "a[href]",
    "button",
    "input",
    "select",
    "textarea",
    "[role='button']",
    "[role='link']",
    "[tabindex]:not([tabindex='-1'])",
  ].join(",");

  refs = new Map();
  const entries = await page.locator(selector).evaluateAll((nodes) =>
    nodes.map((node, index) => {
      const element = node;
      const text = (element.innerText || element.textContent || "").replace(/\s+/g, " ").trim();
      const aria = element.getAttribute("aria-label") || "";
      const placeholder = element.getAttribute("placeholder") || "";
      const role = element.getAttribute("role") || element.tagName.toLowerCase();
      return {
        index,
        role,
        text,
        aria,
        placeholder,
        tag: element.tagName.toLowerCase(),
      };
    }),
  );

  const lines = [
    `URL: ${page.url()}`,
    `Title: ${await page.title()}`,
    "",
    "Interactive elements:",
  ];

  for (const entry of entries) {
    const ref = `@e${entry.index + 1}`;
    refs.set(ref, entry.index);
    const label = entry.aria || entry.text || entry.placeholder || "(unlabeled)";
    lines.push(`${ref} [${entry.role}] ${label}`);
  }

  if (entries.length === 0) {
    lines.push("(none)");
  }

  return {
    text: lines.join("\n"),
    refs: entries.map((entry) => ({
      ref: `@e${entry.index + 1}`,
      role: entry.role,
      label: entry.aria || entry.text || entry.placeholder || "",
    })),
  };
}

function resolveRef(ref) {
  if (!refs.has(ref)) {
    throw new Error(`Unknown or stale ref: ${ref}. Run snapshot again.`);
  }
  return refs.get(ref);
}

async function handleCommand(command, args) {
  const page = getActivePage();

  if (command === "status") {
    return {
      mode,
      current_url: page.url(),
      tabs: getPages().length,
      active_tab: activePageIndex + 1,
      refs: Array.from(refs.keys()),
    };
  }

  if (command === "goto") {
    const url = args[0];
    if (!url) throw new Error("goto requires a URL");
    validateUrl(url);
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
    refs = new Map();
    return {
      current_url: page.url(),
      title: await page.title(),
      navigated: true,
    };
  }

  if (command === "snapshot") {
    const snapshot = await buildSnapshot(page);
    return {
      current_url: page.url(),
      ...snapshot,
    };
  }

  if (command === "screenshot") {
    const name = (args[0] || "browser-shot").replace(/[^a-zA-Z0-9._-]/g, "_");
    const filePath = path.join(artifactsDir, `${name}.png`);
    await page.screenshot({ path: filePath, fullPage: true });
    return {
      current_url: page.url(),
      artifact_path: filePath,
    };
  }

  if (command === "click") {
    const ref = args[0];
    if (!ref) throw new Error("click requires a ref");
    const index = resolveRef(ref);
    const selector = [
      "a[href]",
      "button",
      "input",
      "select",
      "textarea",
      "[role='button']",
      "[role='link']",
      "[tabindex]:not([tabindex='-1'])",
    ].join(",");
    const locator = page.locator(selector).nth(index);
    await locator.click({ timeout: 10000 });
    return {
      clicked: ref,
      current_url: page.url(),
    };
  }

  if (command === "type") {
    const ref = args[0];
    const value = args.slice(1).join(" ");
    if (!ref || value.length === 0) throw new Error("type requires a ref and text");
    const index = resolveRef(ref);
    const selector = [
      "a[href]",
      "button",
      "input",
      "select",
      "textarea",
      "[role='button']",
      "[role='link']",
      "[tabindex]:not([tabindex='-1'])",
    ].join(",");
    const locator = page.locator(selector).nth(index);
    await locator.fill(value, { timeout: 10000 });
    return {
      typed_into: ref,
      chars: value.length,
      current_url: page.url(),
    };
  }

  if (command === "press") {
    const key = args[0];
    if (!key) throw new Error("press requires a key");
    await page.keyboard.press(key);
    return { pressed: key, current_url: page.url() };
  }

  if (command === "wait-for") {
    const target = args[0];
    if (!target) throw new Error("wait-for requires a selector or millisecond value");
    if (/^\d+$/.test(target)) {
      await page.waitForTimeout(Number.parseInt(target, 10));
      return { waited_ms: Number.parseInt(target, 10), current_url: page.url() };
    }
    await page.waitForSelector(target, { timeout: 10000 });
    return { selector: target, current_url: page.url() };
  }

  if (command === "eval") {
    const expr = args.join(" ");
    if (!expr) throw new Error("eval requires JavaScript");
    const value = await page.evaluate(`(() => (${expr}))()`);
    return { value };
  }

  if (command === "console") {
    return { entries: consoleEntries.slice(-50) };
  }

  if (command === "network") {
    return { entries: networkEntries.slice(-50) };
  }

  if (command === "new-tab") {
    const newPage = await context.newPage();
    wirePage(newPage);
    const url = args[0];
    if (url) {
      validateUrl(url);
      await newPage.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
    }
    activePageIndex = getPages().length - 1;
    refs = new Map();
    return {
      active_tab: activePageIndex + 1,
      tabs: getPages().length,
      current_url: newPage.url(),
    };
  }

  if (command === "close-tab") {
    const pages = getPages();
    if (pages.length <= 1) {
      throw new Error("Cannot close the last tab");
    }
    let index = activePageIndex;
    if (args[0]) {
      index = Number.parseInt(args[0], 10) - 1;
    }
    if (Number.isNaN(index) || index < 0 || index >= pages.length) {
      throw new Error(`Invalid tab index: ${args[0]}`);
    }
    await pages[index].close();
    activePageIndex = Math.max(0, Math.min(activePageIndex, getPages().length - 1));
    refs = new Map();
    return {
      active_tab: activePageIndex + 1,
      tabs: getPages().length,
      current_url: getActivePage().url(),
    };
  }

  throw new Error(`unsupported_command:${command}`);
}

const server = http.createServer((req, res) => {
  const addr = server.address();
  const port = typeof addr === "object" && addr ? addr.port : 0;

  if (req.method === "GET" && req.url === "/health") {
    touchState(port);
    sendJson(res, 200, {
      status: "healthy",
      mode,
      current_url: context ? getActivePage().url() : "about:blank",
      tabs: context ? getPages().length : 0,
      version,
    });
    return;
  }

  if (req.method === "POST" && req.url === "/shutdown") {
    if (!isAuthorized(req)) {
      sendJson(res, 401, { error: "unauthorized" });
      return;
    }
    sendJson(res, 200, { ok: true });
    shutdown(0).catch(() => {
      process.exit(0);
    });
    return;
  }

  if (req.method === "POST" && req.url === "/command") {
    if (!isAuthorized(req)) {
      sendJson(res, 401, { error: "unauthorized" });
      return;
    }

    let body = "";
    req.on("data", (chunk) => {
      body += chunk.toString("utf-8");
    });
    req.on("end", async () => {
      touchState(port);
      let payload = {};
      try {
        payload = body ? JSON.parse(body) : {};
      } catch {
        sendJson(res, 400, { ok: false, error: "invalid_json" });
        return;
      }

      try {
        const command = String(payload.command || "");
        const args = Array.isArray(payload.args) ? payload.args.map(String) : [];
        const result = await handleCommand(command, args);
        sendJson(res, 200, { ok: true, command, result });
      } catch (error) {
        sendJson(res, 500, {
          ok: false,
          command: String(payload.command || ""),
          error: error instanceof Error ? error.message : String(error),
        });
      }
    });
    return;
  }

  sendJson(res, 404, { error: "not_found" });
});

async function shutdown(code) {
  if (idleTimer) {
    clearTimeout(idleTimer);
    idleTimer = null;
  }
  try {
    if (context) {
      await context.close();
      context = null;
    }
    if (browser) {
      await browser.close();
      browser = null;
    }
  } catch {}
  try {
    fs.rmSync(stateFile, { force: true });
  } catch {}
  process.exit(code);
}

async function main() {
  await launchBrowser();
  server.listen(0, host, () => {
    const addr = server.address();
    if (!addr || typeof addr === "string") {
      process.stderr.write("Failed to determine daemon port\n");
      process.exit(1);
    }
    writeState(addr.port);
    setIdleTimer();
  });
}

process.on("SIGINT", () => {
  shutdown(0).catch(() => {
    process.exit(0);
  });
});
process.on("SIGTERM", () => {
  shutdown(0).catch(() => {
    process.exit(0);
  });
});

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`);
  process.exit(1);
});
