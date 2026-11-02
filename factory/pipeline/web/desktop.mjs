import { mountGame } from "./game.mjs";
import { renderPicker, readPicker } from "./model_picker.mjs";

const $ = (selector) => document.querySelector(selector);
const game = mountGame();
let token = "";
let currentRun = { status: "idle" };
let selectedProject = null;
let stateVersion = 0;
let lastNotice = "";
let documentVersion = 0;
let modelCatalog = null;
const busy = () => ["running", "waiting"].includes(currentRun.status);

function routeOverrides(selection) {
  return { phases: selection?.phases || {}, agents: selection?.agents || {} };
}

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object")
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stable(value[key])]));
  return value;
}

async function loadModelCatalog() {
  try {
    modelCatalog = await api("/api/models");
    renderPicker($("#new-model-picker"), modelCatalog, {
      role_defaults: modelCatalog.role_defaults, phases: {}, agents: {},
    });
    if (selectedProject)
      renderPicker($("#resume-model-picker"), modelCatalog,
                   selectedProject.model_selection);
  } catch {
    modelCatalog = null;
    renderPicker($("#new-model-picker"), null, {});
  }
}

async function api(path, body) {
  const options =
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Siesta-Token": token,
          },
          body: JSON.stringify(body),
        };
  const response = await fetch(path, {
    ...options,
    signal: AbortSignal.timeout(10000),
  });
  const result = await response.json();
  if (response.status === 403) token = "";
  if (!response.ok)
    throw new Error(result.error || "The request could not be completed");
  return result;
}

function openWindow(id) {
  $(`#${id}`).hidden = false;
  if (innerWidth <= 800) $(`#${id}`).scrollIntoView({ block: "start" });
}

function showView(view) {
  openWindow("main-window");
  document.querySelectorAll(".view").forEach((element) => {
    element.hidden = element.id !== `view-${view}`;
  });
  document.querySelectorAll(".menubar [data-view]").forEach((button) => {
    button.classList.toggle("selected", button.dataset.view === view);
  });
  if (view === "projects") loadProjects();
}

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.view));
});
document.querySelectorAll("[data-open]").forEach((button) => {
  button.addEventListener("click", () => openWindow(button.dataset.open));
});
document.querySelectorAll("[data-hide]").forEach((button) => {
  button.addEventListener("click", () => {
    $(`#${button.dataset.hide}`).hidden = true;
    if (button.dataset.hide === "snake-window") game.pause();
  });
});
$("#notice-dismiss").addEventListener("click", () => {
  $("#notice").hidden = true;
});
$("#notice-action").addEventListener("click", () => {
  showView("activity");
  if (currentRun.status === "waiting") $("#reply").focus();
});

const statusLabels = {
  idle: "Ready",
  running: "Working",
  waiting: "Your turn",
  complete: "Complete",
  failed: "Failed",
  incomplete: "Unverified",
  stopped: "Stopped",
};
const runHeadings = {
  running: "Good things in progress.",
  waiting: "A quick question for you.",
  complete: "Your idea, brought to life.",
  failed: "This run needs a look.",
  incomplete: "There is more work to do.",
  stopped: "Taking a pause.",
};

function renderRun(run) {
  currentRun = run;
  $("#launch-button").disabled = busy() || !token;
  $("#new-model-picker").disabled = busy();
  $("#resume-model-picker").disabled = busy();
  $("#review-policy").disabled = busy();
  $("#resume-button").disabled =
    busy() || !selectedProject?.idea || selectedProject?.stopped || !token;
  $("#run-status").textContent = statusLabels[run.status].toUpperCase();
  $("#tray-status").textContent = `● ${statusLabels[run.status]}`;
  $("#workspace-status").textContent =
    run.status === "idle"
      ? "Ready for your next idea"
      : statusLabels[run.status];
  $("#reply-form").hidden = run.status !== "waiting";
  $("#result-button").hidden = !run.project || busy();
  if (run.status === "idle") {
    $("#run-title").textContent = "A quiet moment.";
    $("#run-description").textContent =
      "Start a project and follow its progress here.";
    $("#console").textContent = "Waiting for your next idea…";
    $("#elapsed").textContent = "00:00";
    $("#run-hint").textContent = "There is no rush. Good work takes a moment.";
    $("#agent-status").textContent = "";
    $("#review-status").textContent = "";
    $("#notice").hidden = true;
    document
      .querySelectorAll("#phase-list li")
      .forEach((element) => element.classList.remove("done", "active"));
    lastNotice = "";
    document.title = "Siesta — your local desktop";
    return;
  }
  $("#run-title").textContent = runHeadings[run.status];
  $("#run-description").textContent = run.idea;
  $("#agent-status").textContent = run.agent
    ? `Agent ${run.agent} · ${run.model || "model unknown"} · ${run.model_phase || "phase unknown"} · tokens ${run.tokens ?? "unknown"} · cost ${run.cost ?? "unknown"}`
    : "Agent and model will appear when Pi starts.";
  const review = run.review;
  $("#review-status").textContent = review
    ? `Review ${review.policy} · round ${review.round} · ${review.status} · ${review.budget?.calls_used ?? 0}/${review.budget?.call_limit ?? "?"} calls · ${Math.floor((review.budget?.active_seconds ?? 0) / 60)}/${Math.floor((review.budget?.active_seconds_limit ?? 0) / 60)} active minutes${review.findings?.length ? ` · Blocking: ${review.findings.map((item) => item.id + " " + item.target).join("; ")}` : ""}`
    : "Review starts after implementation.";
  const minutes = String(Math.floor(run.elapsed / 60)).padStart(2, "0");
  const seconds = String(Math.floor(run.elapsed % 60)).padStart(2, "0");
  $("#elapsed").textContent = `${minutes}:${seconds}`;
  const consolePane = $("#console");
  const atBottom =
    consolePane.scrollHeight -
      consolePane.scrollTop -
      consolePane.clientHeight <
    45;
  if (consolePane.textContent !== run.output) {
    consolePane.textContent = run.output || "Starting the pipeline…";
    if (atBottom) consolePane.scrollTop = consolePane.scrollHeight;
  }
  const phases = [...document.querySelectorAll("#phase-list li")];
  const phaseIndex = phases.findIndex(
    (element) => element.dataset.phase === run.phase,
  );
  phases.forEach((element, index) => {
    element.classList.toggle("active", index === phaseIndex && busy());
    element.classList.toggle(
      "done",
      run.status === "complete" || index < phaseIndex,
    );
  });
  $("#run-hint").textContent = busy()
    ? "Siesta is here. Snake is next door."
    : run.status === "complete"
      ? "Verified by the pipeline. Open the evidence and inspect your files."
      : `Not completed. Check the console and project evidence. Exit: ${run.returncode}.`;
  const noticeKey = `${run.id}:${run.status}:${run.input_id || ""}`;
  if (run.status !== "running" && noticeKey !== lastNotice) {
    lastNotice = noticeKey;
    $("#notice-text").textContent =
      run.status === "waiting"
        ? "Siesta needs your answer."
        : run.status === "complete"
          ? "Your project is ready to inspect."
          : "Siesta stopped before completion. Open activity for details.";
    $("#notice").hidden = false;
    document.title = `${statusLabels[run.status]} — Siesta`;
  } else if (run.status === "running") {
    $("#notice").hidden = true;
    document.title = "Siesta is working…";
  }
}

async function launch(body) {
  if (!token) throw new Error("Wait for the desktop to connect");
  ++stateVersion;
  const run = await api("/api/run", body);
  renderRun(run);
  showView("activity");
}

$("#launch-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#launch-error").textContent = "";
  $("#launch-button").disabled = true;
  try {
    const selection = readPicker($("#new-model-picker"));
    const routes = Object.keys(selection.phases).length || Object.keys(selection.agents).length;
    await launch({ idea: $("#idea").value, auto: $("#auto").checked,
                   ...(routes ? { model_selection: selection } : {}),
                   ...($("#review-policy").value === "deep" ? { review_policy: "deep" } : {}) });
  } catch (error) {
    $("#launch-error").textContent = error.message;
  } finally {
    $("#launch-button").disabled = busy() || !token;
  }
});

$("#reply-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#reply-form button");
  button.disabled = true;
  $("#reply-error").textContent = "";
  ++stateVersion;
  try {
    renderRun(
      await api("/api/reply", {
        run_id: currentRun.id,
        input_id: currentRun.input_id,
        answer: $("#reply").value,
      }),
    );
    $("#reply").value = "";
  } catch (error) {
    $("#reply-error").textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

async function loadProjects() {
  $("#project-error").textContent = "";
  try {
    const { projects } = await api("/api/projects");
    const list = $("#project-list");
    list.replaceChildren();
    if (!projects.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent =
        "An empty desk, full of possibilities. Create your first project to begin.";
      list.append(empty);
    }
    projects.forEach((project) => {
      const button = document.createElement("button");
      button.className = "project-card";
      const icon = document.createElementNS(
        "http://www.w3.org/2000/svg",
        "svg",
      );
      const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
      use.setAttribute("href", "#folder");
      icon.append(use);
      const name = document.createElement("span");
      name.textContent = project.name;
      const state = document.createElement("small");
      state.textContent = `${project.checkpoint || "Not started"} · ${project.verdict || "Not verified"}`;
      name.append(state);
      button.append(icon, name);
      button.addEventListener("click", () => inspectProject(project));
      list.append(button);
    });
    return projects;
  } catch (error) {
    $("#project-error").textContent = error.message;
    return [];
  }
}

async function readDocument(project, name) {
  const version = ++documentVersion;
  $("#document-content").textContent = "Opening document…";
  try {
    const result = await api(
      `/api/document?${new URLSearchParams({ project, name })}`,
    );
    if (version === documentVersion)
      $("#document-content").textContent = result.content || "(Empty document)";
  } catch (error) {
    if (version === documentVersion)
      $("#document-content").textContent = error.message;
  }
}

function inspectProject(project) {
  selectedProject = project;
  ++documentVersion;
  $("#project-detail").hidden = false;
  $("#project-title").textContent = project.name;
  $("#project-state").textContent = project.stopped
    ? "This project has stop.md. Resolve its blocker in the project before resuming."
    : `${project.checkpoint || "No checkpoint"} · ${project.verdict || "Not verified"}`;
  $("#saved-review-policy").textContent = `Review policy: ${project.review_policy || "normal"}`;
  renderPicker($("#resume-model-picker"), modelCatalog, project.model_selection);
  $("#resume-model-picker").disabled = busy();
  $("#resume-button").disabled =
    busy() || !project.idea || project.stopped || !token;
  $("#resume-button").textContent =
    project.checkpoint === "complete"
      ? "Recheck project ↗"
      : "Resume project ↗";
  $("#document-tabs").replaceChildren();
  project.documents.forEach((name) => {
    const button = document.createElement("button");
    button.textContent = name.replace(".siesta/", "");
    button.addEventListener("click", () => readDocument(project.name, name));
    $("#document-tabs").append(button);
  });
  if (project.documents.length)
    readDocument(project.name, project.documents[0]);
  else $("#document-content").textContent = "No documents yet.";
}

$("#resume-button").addEventListener("click", async () => {
  $("#project-error").textContent = "";
  $("#resume-button").disabled = true;
  try {
    const chosen = modelCatalog
      ? readPicker($("#resume-model-picker"))
      : routeOverrides(selectedProject.model_selection);
    const saved = routeOverrides(selectedProject.model_selection);
    const changed = JSON.stringify(stable(chosen)) !== JSON.stringify(stable(saved));
    await launch({ project: selectedProject.name,
                   ...(changed ? { model_selection: chosen } : {}) });
  } catch (error) {
    $("#project-error").textContent = error.message;
  } finally {
    $("#resume-button").disabled =
      busy() || !selectedProject?.idea || selectedProject?.stopped;
  }
});
$("#result-button").addEventListener("click", async () => {
  showView("projects");
  const projects = await loadProjects();
  const project = projects.find((item) => item.name === currentRun.project);
  if (project) inspectProject(project);
});

async function poll() {
  const version = stateVersion;
  try {
    if (!token) token = (await api("/api/session")).token;
    const run = await api("/api/run");
    if (version === stateVersion) renderRun(run);
    $("#connection").textContent = "CONNECTED";
  } catch {
    token = "";
    $("#connection").textContent = "DISCONNECTED";
    $("#workspace-status").textContent =
      "Connection lost — retrying. Keep the server terminal open.";
    $("#launch-button").disabled = true;
    $("#resume-button").disabled = true;
  } finally {
    setTimeout(poll, 1000);
  }
}

function clock() {
  $("#clock").textContent = new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}
clock();
setInterval(clock, 1000);
$("#launch-button").disabled = true;
poll();
loadModelCatalog();
