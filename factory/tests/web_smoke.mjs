// Optional browser check. See docs/desktop.md for the isolated Playwright install.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
const { chromium } = await import(
  process.env.SIESTA_PLAYWRIGHT_MODULE ||
    "../../.runtime/browser-check/node_modules/playwright/index.mjs"
);

const root = fileURLToPath(new URL("../../", import.meta.url));
const server = spawn(
  process.env.PYTHON || "python3",
  ["-u", "factory/tests/web_fixture.py"],
  {
    cwd: root,
    env: { ...process.env, PYTHONPATH: `${root}/factory` },
    stdio: ["ignore", "pipe", "inherit"],
  },
);
let browser;
const errors = [];
const output = `${root}/.runtime/desktop-check`;
try {
  const url = await new Promise((resolve, reject) => {
    let text = "";
    const timeout = setTimeout(
      () => reject(new Error("Fixture startup timed out")),
      10000,
    );
    server.once("error", reject);
    server.once("exit", (code) => {
      clearTimeout(timeout);
      reject(new Error(`Fixture exited: ${code}`));
    });
    server.stdout.on("data", (chunk) => {
      text += chunk.toString();
      const match = text.match(/http:\/\/127\.0\.0\.1:\d+/);
      if (match) {
        clearTimeout(timeout);
        resolve(match[0]);
      }
    });
  });
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.goto(url);
  await page.waitForFunction(
    () => document.querySelector("#connection").textContent === "CONNECTED",
  );
  await mkdir(output, { recursive: true });
  await page.screenshot({ path: `${output}/desktop.png`, fullPage: true });
  await page.locator("#idea").fill("A small timer");
  await page.locator("#launch-button").click();
  await page.locator("#view-activity").waitFor({ state: "visible" });
  const firstRun = await (await page.request.get(`${url}/api/run`)).json();
  await page.locator("#game-start").click();
  await page.locator("#snake").press("ArrowUp");
  await page
    .getByRole("button", { name: "Minimize workspace", exact: true })
    .click();
  await page.locator("#notice").waitFor({ state: "visible" });
  assert.match(
    await page.locator("#notice-text").textContent(),
    /needs your answer/,
  );
  await page.locator("#notice-action").click();
  await page.locator("#reply-form").waitFor({ state: "visible" });
  await page.reload();
  await page.waitForFunction(() =>
    document
      .querySelector("#notice-text")
      .textContent.includes("needs your answer"),
  );
  const reloaded = await (await page.request.get(`${url}/api/run`)).json();
  assert.equal(
    reloaded.id,
    firstRun.id,
    "refresh must not create another process",
  );
  await page.locator("#notice-action").click();
  await page.locator("#reply").fill("Seconds");
  await page.locator("#reply").press("ArrowLeft");
  assert.equal(await page.locator("#reply").inputValue(), "Seconds");
  await page.locator("#reply-form button").click();
  await page.locator("#game-start").click();
  await page.locator("#snake").press("ArrowDown");
  await page.waitForFunction(
    () => document.querySelector("#run-status").textContent === "COMPLETE",
  );
  assert.match(
    await page.locator("#notice-text").textContent(),
    /ready to inspect/,
  );
  await page.locator("#result-button").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#document-content")
      .textContent.includes("Count seconds"),
  );
  assert.equal(
    await page.locator("#document-content img").count(),
    0,
    "documents render as text",
  );
  await page
    .locator("#document-tabs button")
    .filter({ hasText: "requirements.md" })
    .click();
  await page.waitForFunction(() =>
    document
      .querySelector("#document-content")
      .textContent.includes("test_seconds"),
  );
  await page.screenshot({ path: `${output}/evidence.png`, fullPage: true });
  await page.locator("#resume-button").click();
  await page.locator("#view-activity").waitFor({ state: "visible" });
  const resumed = await (await page.request.get(`${url}/api/run`)).json();
  assert.notEqual(resumed.id, firstRun.id);
  await page.waitForFunction(
    () => document.querySelector("#run-status").textContent === "COMPLETE",
  );
  assert.match(
    await page.locator("#console").textContent(),
    /without another interview/,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.menubar [data-view="new"]').click();
  await page.screenshot({ path: `${output}/mobile.png`, fullPage: true });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  await page.locator('.desktop-shortcuts [data-open="snake-window"]').click();
  await page.locator("#game-restart").click();
  await page.locator("#snake").press("Space");
  assert.equal(await page.locator("#snake-status").textContent(), "Paused");
  await page.locator("#game-start").click();
  await page.locator('[data-direction="up"]').click();
  assert.match(await page.locator("#snake-status").textContent(), /Playing/);
  await page.locator("#game-pause").click();
  await page
    .getByRole("button", { name: "Minimize Snake", exact: true })
    .click();
  assert.equal(await page.locator("#snake-window").isVisible(), false);
  await page.locator('.taskbar [data-open="snake-window"]').click();
  assert.equal(await page.locator("#snake-window").isVisible(), true);
  const modelCatalog = {
    models: [
      { id: "local-test:latest", origin: "local", installed: true, pi_registered: true },
      { id: "cloud-test:cloud", origin: "cloud", installed: true, pi_registered: true },
    ],
    phases: ["interview", "specification", "planning", "implementation", "review", "verification"],
    agents: ["planner", "worker", "consultant", "quality-reviewer"],
    role_defaults: {
      planner: { model: "cloud-test:cloud", provider: "ollama" },
      worker: { model: "cloud-test:cloud", provider: "ollama" },
      consultant: { model: "cloud-test:cloud", provider: "ollama" },
    },
  };
  const browserModels = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const launches = [];
  let modelRun = null;
  await browserModels.route("**/api/models", (route) => route.fulfill({ json: modelCatalog }));
  await browserModels.route("**/api/run", (route) => {
    if (route.request().method() === "GET")
      return modelRun ? route.fulfill({ json: modelRun }) : route.continue();
    launches.push(route.request().postDataJSON());
    modelRun = { id: "model-check", status: "running", idea: "Model check",
      phase: "0", elapsed: 0, output: "Starting", project: "model-check" };
    return route.fulfill({ json: modelRun });
  });
  await browserModels.goto(url);
  await browserModels.locator('#new-model-picker select[data-phase="interview"]').waitFor();
  await browserModels.locator("#idea").fill("A small model routing test");
  await browserModels.locator('#new-model-picker select[data-phase="interview"]').selectOption("local-test:latest");
  await browserModels.locator('#new-model-picker select[data-phase="planning"]').selectOption("cloud-test:cloud");
  await browserModels.locator("#new-model-picker details").last().evaluate((node) => { node.open = true; });
  await browserModels.getByRole("button", { name: "Add agent route" }).click();
  await browserModels.locator("#new-model-picker .agent-route-row .agent-phase").selectOption("planning");
  await browserModels.locator("#new-model-picker .agent-route-row .agent-id").selectOption("quality-reviewer");
  await browserModels.locator("#new-model-picker .agent-route-row .model-route").selectOption("local-test:latest");
  await browserModels.locator("#launch-button").click();
  await browserModels.waitForFunction(() => document.querySelector("#view-activity").hidden === false);
  assert.equal(launches[0].model_selection.phases.interview.model, "local-test:latest");
  assert.equal(launches[0].model_selection.phases.planning.model, "cloud-test:cloud");
  assert.equal(launches[0].model_selection.agents.planning["quality-reviewer"].model, "local-test:latest");
  assert.equal(await browserModels.locator("#new-model-picker").evaluate((node) => node.disabled), true);
  await browserModels.close();

  const browserResume = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const resumes = [];
  await browserResume.route("**/api/models", (route) => route.fulfill({ json: modelCatalog }));
  await browserResume.route("**/api/projects", (route) => route.fulfill({ json: { projects: [{
    name: "saved-project", idea: "A saved idea", checkpoint: "phase-3",
    verdict: "", stopped: false, documents: [],
    model_selection: { version: 1, role_defaults: modelCatalog.role_defaults,
      phases: { planning: { model: "cloud-test:cloud", provider: "ollama" } }, agents: {} },
  }] } }));
  await browserResume.route("**/api/run", (route) => {
    if (route.request().method() === "GET") return route.continue();
    resumes.push(route.request().postDataJSON());
    return route.fulfill({ json: { id: "resume-model-check", status: "running", idea: "A saved idea",
      phase: "3", elapsed: 0, output: "Starting", project: "saved-project" } });
  });
  await browserResume.goto(url);
  await browserResume.getByRole("button", { name: "Projects", exact: true }).first().click();
  await browserResume.locator(".project-card").click();
  await browserResume.locator('#resume-model-picker select[data-phase="planning"]').waitFor();
  assert.equal(await browserResume.locator('#resume-model-picker select[data-phase="planning"]').inputValue(),
               "cloud-test:cloud");
  await browserResume.locator('#resume-model-picker select[data-phase="implementation"]').selectOption("local-test:latest");
  await browserResume.locator("#resume-button").click();
  await browserResume.waitForFunction(() => document.querySelector("#view-activity").hidden === false);
  assert.equal(resumes[0].model_selection.phases.implementation.model, "local-test:latest");
  assert.equal(resumes[0].model_selection.phases.planning.model, "cloud-test:cloud");
  await browserResume.close();
  assert.deepEqual(errors, []);
  console.log(
    "PASS: interview, refresh, model routes, resume, evidence, Snake, mobile layout; no browser errors.",
  );
  console.log(`Screenshots: ${output}`);
} finally {
  if (browser) await browser.close();
  server.kill("SIGINT");
  if (server.exitCode === null) await once(server, "exit");
}
