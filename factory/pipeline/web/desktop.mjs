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
let knowledgeVersion = 0;
let knowledgeOffset = 0;
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
  if (view === "knowledge") loadKnowledge(true);
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
  $("#knowledge-save").disabled = busy() || !token;
  $("#resume-button").disabled =
    busy() || !selectedProject?.idea || selectedProject?.stopped || !token;
  $("#edit-project-button").disabled = busy() || !token;
  $("#delete-project-button").disabled = busy() || !token;
  $("#stop-button").hidden = !busy();
  $("#stop-button").disabled = !token;
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
    await launch({ idea: $("#idea").value, name: $("#project-name").value,
                   auto: $("#auto").checked,
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
      name.textContent = project.display_name || project.name;
      const state = document.createElement("small");
      state.textContent = `${project.name} · ${project.checkpoint || "Not started"} · ${project.verdict || "Not verified"}`;
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

async function loadKnowledge(reset = false) {
  if (reset) knowledgeOffset = 0;
  const version = ++knowledgeVersion;
  const scope = $("#knowledge-scope").value;
  const projectSelect = $("#knowledge-project");
  projectSelect.hidden = scope !== "project";
  $("#knowledge-form").hidden = scope !== "global";
  $("#knowledge-error").textContent = "";
  try {
    if (scope === "project") {
      const { projects } = await api("/api/projects");
      const prior = projectSelect.value;
      projectSelect.replaceChildren();
      for (const project of projects) {
        const option = document.createElement("option");
        option.value = project.name;
        option.textContent = project.name;
        projectSelect.append(option);
      }
      if (projects.some((project) => project.name === prior)) projectSelect.value = prior;
    }
    const project = scope === "project" ? projectSelect.value : "";
    if (scope === "project" && !project) {
      $("#knowledge-list").replaceChildren();
      $("#knowledge-count").textContent = "No projects yet.";
      return;
    }
    const params = new URLSearchParams({ scope, q: $("#knowledge-search").value,
                                         offset: String(knowledgeOffset) });
    if (project) params.set("project", project);
    const result = await api(`/api/knowledge?${params}`);
    if (version !== knowledgeVersion) return;
    const list = $("#knowledge-list");
    list.replaceChildren();
    for (const node of result.nodes) {
      const button = document.createElement("button");
      button.className = "project-card";
      const title = document.createElement("span");
      title.textContent = node.summary;
      const type = document.createElement("small");
      type.textContent = `${node.type} · ${node.created_at || ""}`;
      title.append(type);
      button.append(title);
      button.addEventListener("click", () => openKnowledgeItem(scope, project, node.id));
      list.append(button);
    }
    if (!result.nodes.length) list.textContent = "No entries match this search.";
    $("#knowledge-count").textContent = `${result.total} entries · showing ${result.nodes.length ? result.offset + 1 : 0}–${result.offset + result.nodes.length}`;
    $("#knowledge-prev").disabled = knowledgeOffset === 0;
    $("#knowledge-next").disabled = knowledgeOffset + result.nodes.length >= result.total;
  } catch (error) {
    if (version === knowledgeVersion) $("#knowledge-error").textContent = error.message;
  }
}

async function openKnowledgeItem(scope, project, id) {
  const version = ++knowledgeVersion;
  try {
    const params = new URLSearchParams({ scope, id });
    if (project) params.set("project", project);
    const node = await api(`/api/knowledge/item?${params}`);
    if (version !== knowledgeVersion) return;
    $("#knowledge-title").textContent = node.summary;
    $("#knowledge-meta").textContent = `${node.type} · ${node.created_at || ""} · ${node.id}`;
    $("#knowledge-text").textContent = (node.detail || "(No details)") +
      (node.truncated ? "\n\n[display limited to 64 KiB]" : "");
    const relations = $("#knowledge-relations");
    relations.replaceChildren();
    for (const relation of node.relations || []) {
      const button = document.createElement("button");
      button.textContent = `${relation.direction === "out" ? "→" : "←"} ${relation.type}: ${relation.summary}`;
      button.addEventListener("click", () => openKnowledgeItem(scope, project, relation.id));
      relations.append(button);
    }
  } catch (error) {
    if (version === knowledgeVersion) $("#knowledge-error").textContent = error.message;
  }
}

$("#knowledge-scope").addEventListener("change", () => loadKnowledge(true));
$("#knowledge-project").addEventListener("change", () => loadKnowledge(true));
let knowledgeSearchTimer;
$("#knowledge-search").addEventListener("input", () => {
  clearTimeout(knowledgeSearchTimer);
  knowledgeSearchTimer = setTimeout(() => loadKnowledge(true), 250);
});
$("#knowledge-prev").addEventListener("click", () => {
  knowledgeOffset = Math.max(0, knowledgeOffset - 100);
  loadKnowledge();
});
$("#knowledge-next").addEventListener("click", () => {
  knowledgeOffset += 100;
  loadKnowledge();
});
$("#knowledge-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#knowledge-error").textContent = "";
  $("#knowledge-save").disabled = true;
  try {
    const node = await api("/api/knowledge", {
      summary: $("#knowledge-note-title").value,
      detail: $("#knowledge-note-text").value,
    });
    $("#knowledge-note-title").value = "";
    $("#knowledge-note-text").value = "";
    await loadKnowledge(true);
    openKnowledgeItem("global", "", node.id);
  } catch (error) {
    $("#knowledge-error").textContent = error.message;
  } finally {
    $("#knowledge-save").disabled = busy() || !token;
  }
});

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
  $("#project-title").textContent = project.display_name || project.name;
  $("#project-name-form").hidden = true;
  $("#project-state").textContent = project.stopped
    ? "This project has stop.md. Resolve its blocker in the project before resuming."
    : `${project.checkpoint || "No checkpoint"} · ${project.verdict || "Not verified"}`;
  $("#saved-review-policy").textContent = `Review policy: ${project.review_policy || "normal"}`;
  renderPicker($("#resume-model-picker"), modelCatalog, project.model_selection);
  $("#resume-model-picker").disabled = busy();
  $("#resume-button").disabled =
    busy() || !project.idea || project.stopped || !token;
  $("#edit-project-button").disabled = busy() || !token;
  $("#delete-project-button").disabled = busy() || !token;
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

$("#edit-project-button").addEventListener("click", () => {
  $("#project-name-edit").value = selectedProject.display_name || selectedProject.name;
  $("#project-name-form").hidden = false;
  $("#project-name-edit").focus();
});
$("#cancel-project-edit").addEventListener("click", () => {
  $("#project-name-form").hidden = true;
});
$("#project-name-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#project-error").textContent = "";
  try {
    const updated = await api("/api/project/rename", {
      project: selectedProject.name, name: $("#project-name-edit").value,
    });
    inspectProject(updated);
    await loadProjects();
  } catch (error) {
    $("#project-error").textContent = error.message;
  }
});
$("#delete-project-button").addEventListener("click", async () => {
  const project = selectedProject;
  if (!project || !window.confirm(`Delete ${project.display_name || project.name}? It will be moved to the local trash.`)) return;
  $("#project-error").textContent = "";
  try {
    await api("/api/project/delete", { project: project.name, confirm: project.name });
    selectedProject = null;
    $("#project-detail").hidden = true;
    await loadProjects();
  } catch (error) {
    $("#project-error").textContent = error.message;
  }
});

$("#stop-button").addEventListener("click", async () => {
  $("#stop-button").disabled = true;
  ++stateVersion;
  try {
    renderRun(await api("/api/stop", { run_id: currentRun.id }));
  } catch (error) {
    $("#run-hint").textContent = error.message;
    $("#stop-button").disabled = false;
  }
});

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
