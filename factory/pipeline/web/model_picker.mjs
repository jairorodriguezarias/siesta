const phaseRole = {
  interview: "planner", intent_review: "consultant",
  specification: "planner", planning: "planner",
  design_review: "consultant", design_repair: "planner",
  implementation: "worker", issue_review: "consultant",
  review: "consultant", verification: "worker", completion: "worker",
  learning: "consultant", iteration_specification: "planner",
  iteration_planning: "planner",
};
const primaryPhases = new Set([
  "interview", "specification", "planning", "implementation",
  "review", "verification",
]);

function option(value, label, disabled = false) {
  const node = document.createElement("option");
  node.value = value;
  node.textContent = label;
  node.disabled = disabled;
  return node;
}

function modelSelect(catalog, inherited, selected = "") {
  const select = document.createElement("select");
  select.className = "model-route";
  select.append(option("", `Inherited · ${inherited?.model || "configured role"}`));
  let found = !selected;
  for (const model of catalog.models || []) {
    const label = `${model.origin === "cloud" ? "Cloud" : model.origin === "local" ? "Local" : "Unknown"} · ${model.id}`;
    const ready = model.pi_registered && model.installed;
    select.append(option(model.id, `${label}${ready ? "" : " · setup needed"}`, !ready && model.id !== selected));
    if (model.id === selected) found = true;
  }
  if (!found) select.append(option(selected, `Saved · ${selected} · unavailable`));
  select.value = selected;
  select.setAttribute("aria-label", "Model route");
  return select;
}

function phaseRow(phase, catalog, selection) {
  const row = document.createElement("label");
  row.className = "model-route-row";
  const name = document.createElement("span");
  name.textContent = phase.replaceAll("_", " ");
  const role = phaseRole[phase] || "consultant";
  const select = modelSelect(catalog, selection.role_defaults?.[role],
                             selection.phases?.[phase]?.model || "");
  select.dataset.phase = phase;
  row.append(name, select);
  return row;
}

function agentRow(catalog, selection, phase = "", agent = "", model = "") {
  const row = document.createElement("div");
  row.className = "model-route-row agent-route-row";
  const phaseSelect = document.createElement("select");
  phaseSelect.setAttribute("aria-label", "Agent phase");
  for (const value of catalog.phases || []) phaseSelect.append(option(value, value.replaceAll("_", " ")));
  phaseSelect.value = phase || catalog.phases?.[0] || "";
  phaseSelect.className = "agent-phase";
  const agentSelect = document.createElement("select");
  agentSelect.setAttribute("aria-label", "Agent identity");
  for (const value of catalog.agents || []) agentSelect.append(option(value, value));
  agentSelect.value = agent || catalog.agents?.[0] || "";
  agentSelect.className = "agent-id";
  const modelChoice = modelSelect(catalog, selection.phases?.[phase] ||
                                  selection.role_defaults?.[phaseRole[phase] || "consultant"], model);
  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = "Remove";
  remove.setAttribute("aria-label", "Remove agent route");
  remove.addEventListener("click", () => row.remove());
  row.append(phaseSelect, agentSelect, modelChoice, remove);
  return row;
}

export function renderPicker(fieldset, catalog, selection) {
  const host = fieldset.querySelector(".model-picker-fields");
  host.replaceChildren();
  if (!catalog) {
    host.textContent = "Model catalog unavailable. Inherited routes remain in use.";
    return;
  }
  const primary = document.createElement("div");
  primary.className = "model-route-grid";
  const more = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "More phases";
  more.append(summary);
  const extra = document.createElement("div");
  extra.className = "model-route-grid";
  for (const phase of catalog.phases || []) {
    (primaryPhases.has(phase) ? primary : extra).append(phaseRow(phase, catalog, selection));
  }
  more.append(extra);
  const advanced = document.createElement("details");
  const advancedTitle = document.createElement("summary");
  advancedTitle.textContent = "Advanced agent routes";
  const rows = document.createElement("div");
  rows.className = "agent-routes";
  for (const [phase, agents] of Object.entries(selection.agents || {})) {
    for (const [agent, route] of Object.entries(agents)) {
      rows.append(agentRow(catalog, selection, phase, agent, route.model));
    }
  }
  const add = document.createElement("button");
  add.type = "button";
  add.textContent = "Add agent route";
  add.addEventListener("click", () => rows.append(agentRow(catalog, selection)));
  advanced.append(advancedTitle, rows, add);
  host.append(primary, more, advanced);
}

export function readPicker(fieldset) {
  const phases = {}, agents = {};
  for (const select of fieldset.querySelectorAll("select[data-phase]")) {
    if (select.value) phases[select.dataset.phase] = { model: select.value, provider: "ollama" };
  }
  for (const row of fieldset.querySelectorAll(".agent-route-row")) {
    const phase = row.querySelector(".agent-phase").value;
    const agent = row.querySelector(".agent-id").value;
    const model = row.querySelector(".model-route").value;
    if (phase && agent && model) {
      agents[phase] ||= {};
      agents[phase][agent] = { model, provider: "ollama" };
    }
  }
  return { phases, agents };
}
