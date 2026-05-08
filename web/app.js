const state = {
  mode: "overview",
  assetMode: "all",
  selectedSessionId: null,
  highlightedMessageOrdinal: null,
  bootstrap: null,
  currentResults: [],
  currentSnippets: [],
  assets: [],
  projects: [],
  localCwd: "",
  selectedProjectIds: new Set(),
  selectedSessionIds: new Set(),
  selectedFiles: new Map(),
  projectLookup: new Map(),
  sessionLookup: new Map(),
  autoSelectedSessionIds: new Set(),
  fallbackToGlobal: false,
  startupContextEnabled: true,
  startupAutoSelectLimit: 3,
  startupCoachDismissed: false,
  companionStatus: null,
  selectedContextStatus: null,
  selectedContextClearToken: "",
  selectedContextSyncTimer: null,
};

const API_ORIGIN = window.location.protocol === "file:" ? "http://127.0.0.1:37801" : "";

const refs = {
  cwdInput: document.querySelector("#cwdInput"),
  projectGroupSelect: document.querySelector("#projectGroupSelect"),
  limitInput: document.querySelector("#limitInput"),
  daysInput: document.querySelector("#daysInput"),
  toolInput: document.querySelector("#toolInput"),
  fileInput: document.querySelector("#fileInput"),
  commandInput: document.querySelector("#commandInput"),
  errorInput: document.querySelector("#errorInput"),
  queryInput: document.querySelector("#queryInput"),
  queryForm: document.querySelector("#queryForm"),
  modeStrip: document.querySelector("#modeStrip"),
  assetModeStrip: document.querySelector("#assetModeStrip"),
  assetSearchInput: document.querySelector("#assetSearchInput"),
  resultsTitle: document.querySelector("#resultsTitle"),
  resultsList: document.querySelector("#resultsList"),
  resultsEmpty: document.querySelector("#resultsEmpty"),
  snippetList: document.querySelector("#snippetList"),
  snippetsEmpty: document.querySelector("#snippetsEmpty"),
  detailPane: document.querySelector("#detailPane"),
  summaryHeadline: document.querySelector("#summaryHeadline"),
  summaryText: document.querySelector("#summaryText"),
  facetChips: document.querySelector("#facetChips"),
  resultCount: document.querySelector("#resultCount"),
  sessionsMetric: document.querySelector("#sessionsMetric"),
  messagesMetric: document.querySelector("#messagesMetric"),
  groupsMetric: document.querySelector("#groupsMetric"),
  projectsMetric: document.querySelector("#projectsMetric"),
  projectCountPill: document.querySelector("#projectCountPill"),
  projectList: document.querySelector("#projectList"),
  projectsEmpty: document.querySelector("#projectsEmpty"),
  useSelectedProjectsButton: document.querySelector("#useSelectedProjectsButton"),
  scopePill: document.querySelector("#scopePill"),
  heroScopeTitle: document.querySelector("#heroScopeTitle"),
  heroScopeText: document.querySelector("#heroScopeText"),
  railStatusLine: document.querySelector("#railStatusLine"),
  noteCountPill: document.querySelector("#noteCountPill"),
  archiveSummary: document.querySelector("#archiveSummary"),
  obsidianIndexLink: document.querySelector("#obsidianIndexLink"),
  overviewButton: document.querySelector("#overviewButton"),
  allProjectsButton: document.querySelector("#allProjectsButton"),
  currentFolderButton: document.querySelector("#currentFolderButton"),
  startupToggle: document.querySelector("#startupToggle"),
  startupStatusText: document.querySelector("#startupStatusText"),
  companionStatusText: document.querySelector("#companionStatusText"),
  startupCoach: document.querySelector("#startupCoach"),
  startupCoachToggle: document.querySelector("#startupCoachToggle"),
  startupCoachTitle: document.querySelector("#startupCoachTitle"),
  startupCoachText: document.querySelector("#startupCoachText"),
  startupCoachCopyButton: document.querySelector("#startupCoachCopyButton"),
  startupCoachSidebarButton: document.querySelector("#startupCoachSidebarButton"),
  startupCoachDismissButton: document.querySelector("#startupCoachDismissButton"),
  relatedButton: document.querySelector("#relatedButton"),
  summaryButton: document.querySelector("#summaryButton"),
  recentButton: document.querySelector("#recentButton"),
  loadErrorsButton: document.querySelector("#loadErrorsButton"),
  copyVaultPathButton: document.querySelector("#copyVaultPathButton"),
  copyBundleButton: document.querySelector("#copyBundleButton"),
  clearSelectionButton: document.querySelector("#clearSelectionButton"),
  contextSelectionPill: document.querySelector("#contextSelectionPill"),
  selectedPreview: document.querySelector("#selectedPreview"),
  selectedContextStatusText: document.querySelector("#selectedContextStatusText"),
  armSelectedContextButton: document.querySelector("#armSelectedContextButton"),
  handoffPanel: document.querySelector("#handoffPanel"),
  handoffTitle: document.querySelector("#handoffTitle"),
  handoffText: document.querySelector("#handoffText"),
  selectHandoffButton: document.querySelector("#selectHandoffButton"),
  hideHandoffButton: document.querySelector("#hideHandoffButton"),
  assetList: document.querySelector("#assetList"),
  assetStatsPill: document.querySelector("#assetStatsPill"),
  sourceRootsPill: document.querySelector("#sourceRootsPill"),
  toast: document.querySelector("#toast"),
};

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  updateSelectionUI();
  void loadBootstrap();
});

function bindEvents() {
  refs.queryForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await runCurrentMode();
  });

  refs.modeStrip.querySelectorAll("[data-mode]").forEach((button) => {
    button.addEventListener("click", async () => {
      setMode(button.dataset.mode);
      if (state.mode === "overview") {
        await loadOverview();
      }
    });
  });

  refs.assetModeStrip.querySelectorAll("[data-asset-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.assetMode = button.dataset.assetMode;
      refs.assetModeStrip.querySelectorAll("[data-asset-mode]").forEach((item) => {
        item.classList.toggle("is-active", item.dataset.assetMode === state.assetMode);
      });
      renderAssetRows();
    });
  });

  refs.assetSearchInput.addEventListener("input", renderAssetRows);

  refs.cwdInput.addEventListener("change", async () => {
    await loadOverview();
  });

  refs.projectGroupSelect.addEventListener("change", async () => {
    await loadOverview();
  });

  refs.overviewButton.addEventListener("click", async () => {
    setMode("overview");
    await loadOverview();
  });

  refs.allProjectsButton.addEventListener("click", async () => {
    refs.cwdInput.value = "";
    refs.projectGroupSelect.value = "";
    setMode("overview");
    await loadOverview();
  });

  refs.currentFolderButton.addEventListener("click", async () => {
    refs.cwdInput.value = state.localCwd || "";
    refs.projectGroupSelect.value = "";
    setMode("overview");
    await loadOverview();
  });

  document.querySelectorAll("[data-scope-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.dataset.scopeAction === "all") {
        refs.cwdInput.value = "";
      } else {
        refs.cwdInput.value = state.localCwd || "";
      }
      refs.projectGroupSelect.value = "";
      setMode("overview");
      await loadOverview();
    });
  });

  refs.startupToggle.addEventListener("change", async () => {
    await setStartupContextEnabled(refs.startupToggle.checked);
  });

  refs.startupCoachToggle.addEventListener("change", async () => {
    await setStartupContextEnabled(refs.startupCoachToggle.checked);
  });

  refs.startupCoachCopyButton.addEventListener("click", async () => {
    const copied = await copyContextBundle();
    if (copied) {
      showToast("Context copied. Paste it into chat and press Enter.");
      window.setTimeout(() => collapseStartupCoach(), 1600);
    }
  });

  refs.startupCoachSidebarButton.addEventListener("click", () => {
    collapseStartupCoach();
    document.querySelector(".artifact-card")?.scrollIntoView({ block: "start", behavior: "smooth" });
  });

  refs.startupCoachDismissButton.addEventListener("click", () => {
    collapseStartupCoach();
  });

  refs.relatedButton.addEventListener("click", async () => {
    await loadRelated();
  });

  refs.summaryButton.addEventListener("click", async () => {
    setMode("summary");
    await loadSummary();
  });

  refs.recentButton.addEventListener("click", async () => {
    await loadRecent();
  });

  refs.loadErrorsButton.addEventListener("click", async () => {
    setMode("snippets");
    await loadSnippets({ errorOnly: true });
  });

  refs.copyVaultPathButton.addEventListener("click", async () => {
    const vaultPath = state.bootstrap?.status?.obsidian?.root_path;
    if (!vaultPath) {
      showToast("Obsidian vault path is not available yet.");
      return;
    }
    await copyToClipboard(vaultPath, "Vault path copied.");
  });

  refs.copyBundleButton.addEventListener("click", copyContextBundle);
  refs.selectHandoffButton.addEventListener("click", () => {
    selectHandoffText();
    showToast("Text selected. Paste it into the Codex chat box.");
  });
  refs.hideHandoffButton.addEventListener("click", () => {
    refs.handoffPanel.hidden = true;
  });
  refs.clearSelectionButton.addEventListener("click", () => {
    state.selectedProjectIds.clear();
    state.selectedSessionIds.clear();
    state.selectedFiles.clear();
    updateSelectionUI();
    renderProjectRows(state.projects);
    renderSessionRows(state.currentResults);
    renderAssetRows();
    void syncSelectedStartupContext({ clear: true });
  });

  refs.armSelectedContextButton.addEventListener("click", async () => {
    await syncSelectedStartupContext({ force: true });
  });

  refs.useSelectedProjectsButton.addEventListener("click", useSelectedProjects);
}

function setMode(mode) {
  state.mode = mode;
  refs.modeStrip.querySelectorAll("[data-mode]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.mode === mode);
  });
}

function currentFilters({ preserveScope = false } = {}) {
  const rawCwd = refs.cwdInput.value.trim();
  const projectGroup = refs.projectGroupSelect.value.trim();
  const shouldUseGlobalFallback = !preserveScope
    && state.fallbackToGlobal
    && !projectGroup
    && rawCwd === (state.bootstrap?.default_cwd || "");
  return {
    cwd: shouldUseGlobalFallback ? "" : rawCwd,
    rawCwd,
    project_group: projectGroup,
    limit: refs.limitInput.value.trim() || "8",
    days: refs.daysInput.value.trim(),
    tool_name: refs.toolInput.value.trim(),
    file_contains: refs.fileInput.value.trim(),
    command_contains: refs.commandInput.value.trim(),
    error_contains: refs.errorInput.value.trim(),
  };
}

function withQuery(params) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      query.set(key, String(value));
    }
  });
  return query.toString();
}

async function fetchJson(path, options = {}) {
  const headers = {
    Accept: "application/json",
    ...(options.headers || {}),
  };
  const response = await fetch(apiUrl(path), { ...options, headers });
  if (!response.ok) {
    const payload = await response.json().catch(async () => ({ error: await response.text() }));
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return response.json();
}

function apiUrl(path) {
  if (!path.startsWith("/api/")) {
    return path;
  }
  return `${API_ORIGIN}${path}`;
}

async function loadBootstrap() {
  try {
    const payload = await fetchJson("/api/bootstrap");
    state.bootstrap = payload;
    state.localCwd = payload.local_cwd || payload.default_cwd || "";
    state.projects = payload.projects || [];
    state.startupContextEnabled = Boolean(payload.settings?.startup_context_enabled ?? true);
    state.startupAutoSelectLimit = Number(payload.settings?.startup_auto_select_limit || 3);
    state.companionStatus = payload.companion || null;
    state.selectedContextStatus = payload.selected_context || null;
    state.selectedContextClearToken = selectedContextClearToken(state.selectedContextStatus);
    refs.startupToggle.checked = state.startupContextEnabled;
    refs.cwdInput.value = payload.default_cwd || "";
    refs.limitInput.value = "8";
    refs.daysInput.value = "30";
    populateProjectGroups(payload.project_groups || [], payload.default_project_group || "");
    renderStatus(payload.status, payload.overview);
    updateStartupUI();
    renderCompanionStatus(state.companionStatus);
    renderSelectedContextStatus(state.selectedContextStatus);
    renderOverview(payload.overview);
    renderProjectRows(state.projects);
    await loadAssets();
    showStartupCoach();
    window.setInterval(loadCompanionStatus, 3000);
    window.setInterval(loadSelectedContextStatus, 2500);
  } catch (error) {
    refs.summaryHeadline.textContent = "Dashboard failed to load.";
    refs.summaryText.textContent = error.message;
    refs.railStatusLine.textContent = "Index unavailable.";
    showToast(error.message);
  }
}

function populateProjectGroups(groups, selectedValue) {
  refs.projectGroupSelect.innerHTML = "";

  const blankOption = document.createElement("option");
  blankOption.value = "";
  blankOption.textContent = "No merged group";
  refs.projectGroupSelect.append(blankOption);

  groups.forEach((group) => {
    const option = document.createElement("option");
    option.value = group.name;
    option.textContent = group.name;
    if (group.description) {
      option.title = group.description;
    }
    refs.projectGroupSelect.append(option);
  });

  refs.projectGroupSelect.value = selectedValue || "";
}

function renderStatus(status, overview) {
  refs.sessionsMetric.textContent = formatNumber(status.total_sessions || 0);
  refs.messagesMetric.textContent = formatNumber(status.total_messages || 0);
  refs.groupsMetric.textContent = formatNumber(status.project_group_count || 0);
  refs.projectsMetric.textContent = formatNumber(state.projects.length || 0);
  refs.noteCountPill.textContent = `${formatNumber(status.obsidian?.note_count || 0)} notes`;
  refs.sourceRootsPill.textContent = `${formatNumber(status.session_roots?.length || 0)} roots`;

  const scope = overview?.project_group
    ? `Merged group: ${overview.project_group}`
    : overview?.cwd
      ? "Current folder"
      : "All projects";
  refs.scopePill.textContent = scope;
  refs.heroScopeTitle.textContent = overview?.project_group || (overview?.cwd ? "Current folder focus" : "All indexed projects");
  refs.heroScopeText.textContent = overview?.cwd || "Search every indexed Codex chat on this machine and any configured synced session roots.";
  refs.railStatusLine.textContent = status.latest_session_started_at
    ? `Latest indexed session: ${formatDate(status.latest_session_started_at)}`
    : "No indexed sessions yet.";

  refs.archiveSummary.textContent = status.obsidian?.root_path
    ? `Archive root: ${status.obsidian.root_path}`
    : "Obsidian export is disabled.";

  refs.obsidianIndexLink.href = status.obsidian?.index_uri || "#";
  updateSelectionUI();
}

function renderOverview(overview) {
  state.fallbackToGlobal = Boolean(overview?.fallback_to_global);
  state.currentResults = overview?.related || [];
  state.currentSnippets = overview?.error_snippets || [];
  rememberSessions(state.currentResults);
  if (state.startupContextEnabled) {
    applyStartupAutoSelection(state.currentResults);
  }
  updateStartupUI();

  refs.resultsTitle.textContent = overview?.project_group
    ? `Sessions in ${overview.project_group}`
    : overview?.cwd
      ? "Current folder sessions"
      : "All recent Codex chats";

  refs.summaryHeadline.textContent = overview?.summary?.headline || "Current folder memory is ready.";
  refs.summaryText.textContent = overview?.summary?.decision_summary || "No decision summary available yet.";
  refs.resultCount.textContent = `${state.currentResults.length} results`;

  const chipItems = [
    ...(overview?.summary?.top_tools || []).slice(0, 3).map((value) => ({ label: "Tool", value })),
    ...(overview?.summary?.top_files || []).slice(0, 2).map((value) => ({ label: "File", value })),
    ...(overview?.summary?.top_errors || []).slice(0, 2).map((value) => ({ label: "Error", value })),
  ];
  renderChips(chipItems);
  updateSelectionUI();
  renderSessionRows(state.currentResults);
  renderSnippetRows(state.currentSnippets);
}

function renderProjectRows(rows) {
  rememberProjects(rows);
  refs.projectList.innerHTML = "";
  refs.projectsEmpty.hidden = rows.length > 0;
  refs.projectCountPill.textContent = `${formatNumber(rows.length)} projects`;
  refs.projectsMetric.textContent = formatNumber(rows.length);
  updateProjectUseButton();

  rows.forEach((row) => {
    const article = document.createElement("article");
    article.className = "project-row";
    article.dataset.projectId = row.id || "";
    if (row.primary_cwd && refs.cwdInput.value.trim() === row.primary_cwd) {
      article.classList.add("is-active");
    }
    if (state.selectedProjectIds.has(row.id)) {
      article.classList.add("is-selected");
    }
    article.innerHTML = `
      <label class="project-select" title="Select project context">
        <input type="checkbox" data-action="select-project" data-project="${escapeAttribute(row.id || "")}" ${state.selectedProjectIds.has(row.id) ? "checked" : ""}>
        <span aria-hidden="true"></span>
      </label>
      <button class="project-open" type="button" data-action="open-project">
        <span class="project-title-line">
          <span class="folder-glyph" aria-hidden="true"></span>
          <span class="project-name">${escapeHtml(row.name || "No working directory")}</span>
          <span class="project-time">${escapeHtml(formatRelativeDate(row.latest_started_at))}</span>
        </span>
        <span class="project-thread-line">
        <span class="thread-title">${escapeHtml(row.latest_title || "No recent title.")}</span>
        <span class="thread-count">${formatNumber(row.session_count)}</span>
        </span>
      </button>
      <button class="project-use-row" type="button" data-action="use-project">Use</button>
      <button class="project-copy" type="button" data-action="copy-project-path" aria-label="Copy project path"></button>
    `;

    article.querySelector("[data-action='select-project']").addEventListener("change", (event) => {
      if (event.currentTarget.checked) {
        state.selectedProjectIds.add(row.id);
      } else {
        state.selectedProjectIds.delete(row.id);
      }
      article.classList.toggle("is-selected", event.currentTarget.checked);
      updateSelectionUI();
      updateProjectUseButton();
    });

    const openProject = async (event) => {
      event.preventDefault();
      article.classList.add("is-loading");
      article.querySelectorAll("[data-action='open-project']").forEach((button) => {
        button.disabled = true;
      });
      try {
        refs.cwdInput.value = row.primary_cwd || "";
        refs.projectGroupSelect.value = "";
        setMode("overview");
        await loadOverview();
        refs.summaryHeadline.scrollIntoView({ block: "start", behavior: "smooth" });
        showToast(`Opened ${row.name || "project"}.`);
      } catch (error) {
        showToast(error.message);
      } finally {
        article.classList.remove("is-loading");
        article.querySelectorAll("[data-action='open-project']").forEach((button) => {
          button.disabled = false;
        });
      }
    };

    article.querySelectorAll("[data-action='open-project']").forEach((button) => {
      button.addEventListener("click", openProject);
    });
    article.querySelector("[data-action='use-project']").addEventListener("click", async (event) => {
      event.preventDefault();
      state.selectedProjectIds.add(row.id);
      updateSelectionUI();
      renderProjectRows(state.projects);
      await useSelectedProjects();
    });
    article.querySelector("[data-action='copy-project-path']").addEventListener("click", async (event) => {
      event.preventDefault();
      await copyToClipboard(row.primary_cwd || "", "Project path copied.", {
        title: "Project path ready",
      });
    });
    refs.projectList.append(article);
  });
}

function rememberProjects(rows) {
  rows.forEach((row) => {
    if (row?.id) {
      state.projectLookup.set(row.id, row);
    }
  });
}

function updateProjectUseButton() {
  refs.useSelectedProjectsButton.disabled = state.selectedProjectIds.size === 0;
  refs.useSelectedProjectsButton.textContent = state.selectedProjectIds.size
    ? `Use ${formatNumber(state.selectedProjectIds.size)}`
    : "Use selected";
}

async function useSelectedProjects() {
  if (!state.selectedProjectIds.size) {
    showToast("Select one or more projects first.");
    return;
  }
  await syncSelectedStartupContext({ force: true });
  await copyContextBundle();
}

function renderChips(items) {
  refs.facetChips.innerHTML = "";
  items.forEach((item) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = `${item.label}: ${item.value}`;
    refs.facetChips.append(chip);
  });
}

function rememberSessions(rows) {
  rows.forEach((row) => {
    if (row?.session_id) {
      state.sessionLookup.set(row.session_id, row);
    }
  });
}

function renderSessionRows(rows) {
  rememberSessions(rows);
  refs.resultsList.innerHTML = "";
  refs.resultsEmpty.hidden = rows.length > 0;

  rows.forEach((row) => {
    const article = document.createElement("article");
    article.className = "session-row";
    if (row.session_id === state.selectedSessionId) {
      article.classList.add("is-active");
    }
    if (state.selectedSessionIds.has(row.session_id)) {
      article.classList.add("is-selected");
    }

    const tools = (row.tool_names || []).slice(0, 3).map((value) => `<span class="meta-pill">${escapeHtml(value)}</span>`).join("");
    const groups = (row.project_groups || []).slice(0, 2).map((value) => `<span class="meta-pill">${escapeHtml(value)}</span>`).join("");
    const primarySummary = row.decision_summary || row.summary || "No summary available.";

    article.innerHTML = `
      <div class="row-head">
        <div>
          <h4>${escapeHtml(row.title || row.session_id)}</h4>
          <p class="row-summary">${escapeHtml(primarySummary)}</p>
        </div>
        <div class="detail-meta">
          <span class="meta-pill">${formatDate(row.started_at)}</span>
        </div>
      </div>
      <div class="row-meta">
        ${groups}
        ${tools}
        ${row.cwd ? `<span class="meta-pill">${escapeHtml(shortenPath(row.cwd))}</span>` : ""}
      </div>
      <div class="row-actions">
        <label class="select-line">
          <input type="checkbox" data-action="select-session" data-session="${escapeAttribute(row.session_id)}" ${state.selectedSessionIds.has(row.session_id) ? "checked" : ""}>
          Use in context
        </label>
        <button class="text-link" type="button" data-action="inspect" data-session="${escapeAttribute(row.session_id)}">Inspect session</button>
        ${row.obsidian_uri ? `<a class="text-link" href="${escapeAttribute(row.obsidian_uri)}">Open Obsidian</a>` : ""}
        ${row.file_path ? `<button class="text-link" type="button" data-action="copy-path" data-path="${escapeAttribute(row.file_path)}">Copy transcript path</button>` : ""}
      </div>
    `;

    article.querySelectorAll("[data-action='select-session']").forEach((checkbox) => {
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) {
          state.selectedSessionIds.add(row.session_id);
        } else {
          state.selectedSessionIds.delete(row.session_id);
        }
        updateSelectionUI();
        renderSessionRows(state.currentResults);
      });
    });

    article.querySelectorAll("[data-action='inspect']").forEach((button) => {
      button.addEventListener("click", async () => {
        state.highlightedMessageOrdinal = null;
        await loadSession(button.dataset.session);
      });
    });

    article.querySelectorAll("[data-action='copy-path']").forEach((button) => {
      button.addEventListener("click", async () => {
        await copyToClipboard(button.dataset.path, "Transcript path copied.", {
          title: "Transcript path ready",
        });
      });
    });

    refs.resultsList.append(article);
  });
}

function renderSnippetRows(rows) {
  rememberSessions(rows);
  refs.snippetList.innerHTML = "";
  refs.snippetsEmpty.hidden = rows.length > 0;

  rows.forEach((row) => {
    const article = document.createElement("article");
    article.className = "snippet-row";
    article.innerHTML = `
      <div class="row-head">
        <div>
          <h4>${escapeHtml(row.title || row.session_id)}</h4>
          <p class="snippet-preview">${escapeHtml(row.snippet || row.full_text || "")}</p>
        </div>
        <div class="detail-meta">
          <span class="meta-pill">${escapeHtml(row.message_role || "message")}</span>
          <span class="meta-pill">${formatDate(row.started_at)}</span>
        </div>
      </div>
      <div class="row-actions">
        <button class="text-link" type="button" data-action="open-snippet" data-session="${escapeAttribute(row.session_id)}" data-ordinal="${row.message_ordinal || ""}">Open in inspector</button>
        <button class="text-link" type="button" data-action="select-snippet-session" data-session="${escapeAttribute(row.session_id)}">Use session in context</button>
        ${row.obsidian_uri ? `<a class="text-link" href="${escapeAttribute(row.obsidian_uri)}">Open Obsidian</a>` : ""}
      </div>
    `;

    article.querySelector("[data-action='open-snippet']").addEventListener("click", async (event) => {
      state.highlightedMessageOrdinal = Number(event.currentTarget.dataset.ordinal || 0) || null;
      await loadSession(event.currentTarget.dataset.session);
    });

    article.querySelector("[data-action='select-snippet-session']").addEventListener("click", () => {
      state.selectedSessionIds.add(row.session_id);
      updateSelectionUI();
      renderSessionRows(state.currentResults);
    });

    refs.snippetList.append(article);
  });
}

async function runCurrentMode() {
  if (state.mode === "overview") {
    await loadOverview();
    return;
  }
  if (state.mode === "summary") {
    await loadSummary();
    return;
  }
  if (state.mode === "snippets") {
    await loadSnippets();
    return;
  }
  await loadSearch(state.mode);
}

async function loadOverview() {
  const filters = currentFilters({ preserveScope: true });
  const query = withQuery({
    cwd: filters.rawCwd,
    project_group: filters.project_group,
    limit: filters.limit,
  });
  const payload = await fetchJson(`/api/overview?${query}`);
  renderStatus(state.bootstrap?.status || {}, payload);
  renderOverview(payload);
  await loadProjects();
  await loadAssets();
}

async function loadProjects() {
  const payload = await fetchJson("/api/projects?limit=250");
  state.projects = payload.projects || [];
  renderProjectRows(state.projects);
}

async function loadRelated() {
  const filters = currentFilters();
  const query = withQuery({
    ...filters,
    query: refs.queryInput.value.trim(),
  });
  const payload = await fetchJson(`/api/related?${query}`);
  refs.resultsTitle.textContent = "Related sessions";
  refs.summaryHeadline.textContent = payload?.brief || "Related sessions";
  refs.summaryText.textContent = payload?.sessions?.[0]?.decision_summary || "No decision summary available.";
  refs.resultCount.textContent = `${payload.sessions?.length || 0} results`;
  renderChips([]);
  state.currentResults = payload.sessions || [];
  renderSessionRows(state.currentResults);
  await loadAssets();
  if (payload.sessions?.length) {
    state.highlightedMessageOrdinal = null;
    await loadSession(payload.sessions[0].session_id);
  }
}

async function loadRecent() {
  const filters = currentFilters();
  const query = withQuery(filters);
  const payload = await fetchJson(`/api/recent?${query}`);
  refs.resultsTitle.textContent = "Recent sessions";
  refs.summaryHeadline.textContent = "Recent memory";
  refs.summaryText.textContent = "Latest indexed sessions for the current scope.";
  refs.resultCount.textContent = `${payload.rows?.length || 0} results`;
  renderChips([]);
  state.currentResults = payload.rows || [];
  renderSessionRows(state.currentResults);
  await loadAssets();
  if (payload.rows?.length) {
    state.highlightedMessageOrdinal = null;
    await loadSession(payload.rows[0].session_id);
  }
}

async function loadSummary() {
  const filters = currentFilters();
  const query = withQuery({
    ...filters,
    query: refs.queryInput.value.trim(),
  });
  const payload = await fetchJson(`/api/summary?${query}`);
  refs.resultsTitle.textContent = "Last-time session set";
  refs.summaryHeadline.textContent = payload.headline || "No prior memory matched.";
  refs.summaryText.textContent = payload.decision_summary || "No decision summary available.";
  refs.resultCount.textContent = `${payload.sessions?.length || 0} results`;

  const chipItems = [
    ...(payload.top_tools || []).slice(0, 3).map((value) => ({ label: "Tool", value })),
    ...(payload.top_files || []).slice(0, 2).map((value) => ({ label: "File", value })),
    ...(payload.top_errors || []).slice(0, 2).map((value) => ({ label: "Error", value })),
  ];
  renderChips(chipItems);
  state.currentResults = payload.sessions || [];
  renderSessionRows(state.currentResults);
  await loadAssets();
  if (payload.sessions?.length) {
    state.highlightedMessageOrdinal = null;
    await loadSession(payload.sessions[0].session_id);
  }
}

async function loadSearch(mode) {
  const filters = currentFilters();
  const queryValue = refs.queryInput.value.trim();
  if (!queryValue) {
    showToast("Enter a search query first.");
    return;
  }

  const query = withQuery({
    ...filters,
    query: queryValue,
    mode: mode === "keyword" ? "keyword" : "hybrid",
  });

  const payload = await fetchJson(`/api/search?${query}`);
  refs.resultsTitle.textContent = mode === "keyword" ? "Keyword results" : "Hybrid recall";
  refs.summaryHeadline.textContent = queryValue;
  refs.summaryText.textContent = mode === "keyword"
    ? "Exact keyword and FTS matches."
    : "Combined keyword ranking and semantic recall.";
  refs.resultCount.textContent = `${payload.rows?.length || 0} results`;
  renderChips([]);
  state.currentResults = payload.rows || [];
  renderSessionRows(state.currentResults);
  await loadAssets();
  if (payload.rows?.length) {
    state.highlightedMessageOrdinal = null;
    await loadSession(payload.rows[0].session_id);
  }
}

async function loadSnippets({ errorOnly = false } = {}) {
  const filters = currentFilters();
  const query = withQuery({
    ...filters,
    query: refs.queryInput.value.trim(),
    error_only: errorOnly,
  });
  const payload = await fetchJson(`/api/snippets?${query}`);
  refs.resultsTitle.textContent = "Exact transcript snippets";
  refs.summaryHeadline.textContent = errorOnly
    ? "Error-focused transcript recall"
    : "Exact transcript snippets";
  refs.summaryText.textContent = "Snippet rows keep the exact transcript line available in the inspector.";
  refs.resultCount.textContent = `${payload.rows?.length || 0} results`;
  renderChips([]);
  state.currentSnippets = payload.rows || [];
  renderSnippetRows(state.currentSnippets);
  await loadAssets();
  if (payload.rows?.length) {
    state.highlightedMessageOrdinal = Number(payload.rows[0].message_ordinal || 0) || null;
    await loadSession(payload.rows[0].session_id);
  }
}

async function loadAssets() {
  const filters = currentFilters({ preserveScope: true });
  const query = withQuery({
    cwd: filters.rawCwd,
    project_group: filters.project_group,
    days: filters.days,
    asset_limit: 160,
  });
  try {
    const payload = await fetchJson(`/api/context-assets?${query}`);
    state.assets = payload.items || [];
    renderAssetRows();
  } catch (error) {
    refs.assetList.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
  }
}

async function loadSession(sessionId) {
  if (!sessionId) {
    return;
  }
  try {
    const payload = await fetchJson(`/api/session/${encodeURIComponent(sessionId)}?max_messages=60`);
    state.selectedSessionId = sessionId;
    rememberSessions([payload]);
    renderSessionRows(state.currentResults);
    renderDetail(payload);
  } catch (error) {
    showToast(error.message);
  }
}

function renderAssetRows() {
  const searchValue = refs.assetSearchInput.value.trim().toLowerCase();
  const rows = state.assets.filter((asset) => {
    if (state.assetMode === "image" && asset.kind !== "image") {
      return false;
    }
    if (state.assetMode === "existing" && !asset.exists) {
      return false;
    }
    if (state.assetMode === "selected" && !state.selectedFiles.has(asset.id)) {
      return false;
    }
    if (!searchValue) {
      return true;
    }
    const haystack = `${asset.label} ${asset.path} ${asset.extension} ${asset.kind}`.toLowerCase();
    return haystack.includes(searchValue);
  });

  refs.assetList.innerHTML = "";
  refs.assetStatsPill.textContent = `${formatNumber(rows.length)} files`;
  if (!rows.length) {
    refs.assetList.innerHTML = "<div class=\"empty-state\">No referenced project files or images matched this scope.</div>";
    return;
  }

  rows.forEach((asset) => {
    const selected = state.selectedFiles.has(asset.id);
    const article = document.createElement("article");
    article.className = `asset-row${selected ? " is-selected" : ""}`;
    const thumb = asset.kind === "image" && asset.exists
      ? `<img alt="" src="${escapeAttribute(assetPreviewUrl(asset.path))}">`
      : `<span>${escapeHtml(assetIconLabel(asset))}</span>`;

    article.innerHTML = `
      <input type="checkbox" aria-label="Select ${escapeAttribute(asset.label)}" ${selected ? "checked" : ""}>
      <div class="asset-thumb ${escapeAttribute(asset.kind || "file")}">${thumb}</div>
      <div class="asset-main">
        <span class="asset-name" title="${escapeAttribute(asset.label)}">${escapeHtml(asset.label)}</span>
        <button class="asset-path" type="button" title="${escapeAttribute(asset.path)}">${escapeHtml(asset.path)}</button>
      </div>
      <span class="asset-kind">${escapeHtml(asset.kind)}${asset.exists ? "" : " missing"}</span>
    `;

    article.querySelector("input").addEventListener("change", (event) => {
      if (event.currentTarget.checked) {
        state.selectedFiles.set(asset.id, asset);
      } else {
        state.selectedFiles.delete(asset.id);
      }
      updateSelectionUI();
      renderAssetRows();
    });

    article.querySelector(".asset-path").addEventListener("click", async () => {
      await copyToClipboard(asset.path, "File path copied.", {
        title: "File path ready",
      });
      if (!state.selectedFiles.has(asset.id)) {
        state.selectedFiles.set(asset.id, asset);
        updateSelectionUI();
        renderAssetRows();
      }
    });

    refs.assetList.append(article);
  });
}

function clearAutoSelectedSessions() {
  state.autoSelectedSessionIds.forEach((sessionId) => {
    state.selectedSessionIds.delete(sessionId);
  });
  state.autoSelectedSessionIds.clear();
}

function applyStartupAutoSelection(rows) {
  clearAutoSelectedSessions();
  if (!state.startupContextEnabled) {
    return;
  }
  rows.slice(0, state.startupAutoSelectLimit).forEach((row) => {
    if (row?.session_id) {
      state.selectedSessionIds.add(row.session_id);
      state.autoSelectedSessionIds.add(row.session_id);
    }
  });
}

function updateStartupUI() {
  refs.startupToggle.checked = state.startupContextEnabled;
  refs.startupCoachToggle.checked = state.startupContextEnabled;
  refs.startupStatusText.textContent = state.startupContextEnabled
    ? `Auto-selects ${formatNumber(state.startupAutoSelectLimit)} recent rows`
    : "Manual select";
  const selectedCount = state.startupContextEnabled ? state.autoSelectedSessionIds.size : 0;
  refs.startupCoachTitle.textContent = state.startupContextEnabled
    ? `${formatNumber(selectedCount)} context rows ready`
    : "Startup context is off";
  refs.startupCoachText.textContent = state.startupContextEnabled
    ? "Copy the compact context pack, paste it into the first chat message, then send."
    : "Turn this on to auto-select recent memory before your first message.";
  refs.startupCoachCopyButton.disabled = !state.startupContextEnabled;
}

async function saveDashboardSettings() {
  try {
    await fetchJson("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        startup_context_enabled: state.startupContextEnabled,
        startup_auto_select_limit: state.startupAutoSelectLimit,
      }),
    });
  } catch (error) {
    showToast(error.message);
  }
}

async function loadCompanionStatus() {
  try {
    const payload = await fetchJson("/api/companion-status");
    state.companionStatus = payload.companion || null;
    renderCompanionStatus(state.companionStatus);
  } catch {
    renderCompanionStatus(null);
  }
}

async function loadSelectedContextStatus() {
  try {
    const payload = await fetchJson("/api/selected-startup-context");
    state.selectedContextStatus = payload.selected_context || null;
    const clearToken = selectedContextClearToken(state.selectedContextStatus);
    if (clearToken && clearToken !== state.selectedContextClearToken) {
      state.selectedContextClearToken = clearToken;
      clearDashboardStartupSelection(state.selectedContextStatus?.clear_signal || null);
    } else {
      state.selectedContextClearToken = clearToken || state.selectedContextClearToken;
      renderSelectedContextStatus(state.selectedContextStatus);
    }
  } catch {
    renderSelectedContextStatus(state.selectedContextStatus);
  }
}

function renderCompanionStatus(status) {
  if (!status?.connected) {
    refs.companionStatusText.textContent = "Companion not connected";
    refs.companionStatusText.classList.remove("is-active");
    return;
  }
  refs.companionStatusText.textContent = status.codex_focused
    ? "Companion: Codex active"
    : "Companion: running";
  refs.companionStatusText.classList.toggle("is-active", Boolean(status.codex_focused));
}

async function setStartupContextEnabled(enabled) {
  state.startupContextEnabled = Boolean(enabled);
  if (state.startupContextEnabled) {
    applyStartupAutoSelection(state.currentResults);
    state.startupCoachDismissed = false;
    showStartupCoach();
  } else {
    clearAutoSelectedSessions();
  }
  updateStartupUI();
  updateSelectionUI();
  renderSessionRows(state.currentResults);
  await syncSelectedStartupContext();
  await saveDashboardSettings();
}

function showStartupCoach() {
  if (state.startupCoachDismissed) {
    return;
  }
  refs.startupCoach.hidden = false;
}

function collapseStartupCoach() {
  state.startupCoachDismissed = true;
  refs.startupCoach.hidden = true;
}

function assetIconLabel(asset) {
  const extension = String(asset.extension || "").replace(".", "").slice(0, 3);
  if (extension) {
    return extension;
  }
  const kind = String(asset.kind || "file");
  return kind.slice(0, 3);
}

function assetPreviewUrl(path) {
  return apiUrl(`/api/asset-preview?path=${encodeURIComponent(path)}`);
}

function renderDetail(session) {
  if (!session) {
    refs.detailPane.className = "detail-pane empty";
    refs.detailPane.textContent = "No session detail available.";
    return;
  }

  refs.detailPane.className = "detail-pane";
  refs.detailPane.innerHTML = "";

  const blocks = [];
  blocks.push(`
    <div class="detail-block">
      <h2 class="detail-title">${escapeHtml(session.title || session.session_id)}</h2>
      <div class="detail-meta">
        <span class="meta-pill">${formatDate(session.started_at)}</span>
        ${session.cwd ? `<span class="meta-pill">${escapeHtml(shortenPath(session.cwd))}</span>` : ""}
        ${(session.project_groups || []).slice(0, 2).map((value) => `<span class="meta-pill">${escapeHtml(value)}</span>`).join("")}
      </div>
      <div class="row-actions">
        <label class="select-line">
          <input type="checkbox" data-detail-select="${escapeAttribute(session.session_id)}" ${state.selectedSessionIds.has(session.session_id) ? "checked" : ""}>
          Use in context
        </label>
        ${session.obsidian_uri ? `<a class="text-link" href="${escapeAttribute(session.obsidian_uri)}">Open Obsidian</a>` : ""}
        ${session.file_path ? `<button class="text-link" type="button" data-detail-copy="${escapeAttribute(session.file_path)}">Copy transcript path</button>` : ""}
      </div>
    </div>
  `);

  blocks.push(`
    <div class="detail-block">
      <h4>Summary</h4>
      <p class="summary-copy">${escapeHtml(session.summary || "No summary available.")}</p>
    </div>
  `);

  blocks.push(`
    <div class="detail-block">
      <h4>Decision</h4>
      <p class="summary-copy">${escapeHtml(session.decision_summary || "No decision summary available.")}</p>
    </div>
  `);

  blocks.push(renderDetailList("Tools", session.tool_names || []));
  blocks.push(renderDetailList("Files", session.files_touched || []));
  blocks.push(renderDetailList("Commands", session.commands_seen || []));
  blocks.push(renderDetailList("Errors", session.error_signatures || []));

  const messageRows = (session.messages || []).map((message) => {
    const highlighted = state.highlightedMessageOrdinal && Number(message.ordinal) === Number(state.highlightedMessageOrdinal);
    return `
      <article class="message-row${highlighted ? " highlight" : ""}">
        <div class="detail-meta">
          <span class="meta-pill">${escapeHtml(message.role || "message")}</span>
          <span class="meta-pill">${escapeHtml(message.kind || "text")}</span>
          <span class="meta-pill">#${escapeHtml(String(message.ordinal || ""))}</span>
        </div>
        <pre>${escapeHtml(message.text || "")}</pre>
      </article>
    `;
  }).join("");

  blocks.push(`
    <div class="detail-block">
      <h4>Transcript</h4>
      <div class="message-stream">${messageRows || "<p class='muted-copy'>No messages available.</p>"}</div>
    </div>
  `);

  refs.detailPane.innerHTML = blocks.join("");
  refs.detailPane.querySelectorAll("[data-detail-copy]").forEach((button) => {
    button.addEventListener("click", async () => {
      await copyToClipboard(button.dataset.detailCopy, "Transcript path copied.", {
        title: "Transcript path ready",
      });
    });
  });
  refs.detailPane.querySelectorAll("[data-detail-select]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        state.selectedSessionIds.add(checkbox.dataset.detailSelect);
      } else {
        state.selectedSessionIds.delete(checkbox.dataset.detailSelect);
      }
      updateSelectionUI();
      renderSessionRows(state.currentResults);
    });
  });
}

function renderDetailList(title, values) {
  const items = values.length
    ? values.map((value) => `<span class="detail-tag">${escapeHtml(value)}</span>`).join("")
    : "<span class='muted-copy'>None</span>";
  return `
    <div class="detail-block">
      <h4>${escapeHtml(title)}</h4>
      <div class="detail-list">${items}</div>
    </div>
  `;
}

function updateSelectionUI() {
  const selectedProjectCount = state.selectedProjectIds.size;
  const selectedSessionCount = state.selectedSessionIds.size;
  const selectedFileCount = state.selectedFiles.size;
  const total = selectedProjectCount + selectedSessionCount + selectedFileCount;
  refs.contextSelectionPill.textContent = `${formatNumber(total)} selected`;
  updateProjectUseButton();

  if (!total) {
    refs.selectedPreview.textContent = "No projects, memory rows, or files selected.";
    renderSelectedContextStatus(state.selectedContextStatus);
    return;
  }

  const projectLabels = Array.from(state.selectedProjectIds)
    .slice(0, 3)
    .map((projectId) => state.projectLookup.get(projectId)?.name || projectId);
  const sessionLabels = Array.from(state.selectedSessionIds)
    .slice(0, 3)
    .map((sessionId) => state.sessionLookup.get(sessionId)?.title || sessionId);
  const fileLabels = Array.from(state.selectedFiles.values())
    .slice(0, 3)
    .map((asset) => asset.label);

  refs.selectedPreview.innerHTML = `
    <div class="selection-line"><span>Projects</span><strong>${formatNumber(selectedProjectCount)}</strong></div>
    <div class="selection-line"><span>Memory rows</span><strong>${formatNumber(selectedSessionCount)}</strong></div>
    <div class="selection-line"><span>Files/images</span><strong>${formatNumber(selectedFileCount)}</strong></div>
    ${projectLabels.length ? `<div class="selection-items">${escapeHtml(projectLabels.join(" | "))}</div>` : ""}
    ${sessionLabels.length ? `<div class="selection-items">${escapeHtml(sessionLabels.join(" | "))}</div>` : ""}
    ${fileLabels.length ? `<div class="selection-items">${escapeHtml(fileLabels.join(" | "))}</div>` : ""}
  `;
  scheduleSelectedStartupContextSync();
}

async function copyContextBundle() {
  const payload = selectedContextPayload();

  await syncSelectedStartupContext();

  try {
    const bundle = await fetchJson("/api/context-bundle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return await copyToClipboard(bundle.text, `Context bundle copied (${formatNumber(bundle.character_count)} chars).`, {
      title: "Context bundle ready",
      reveal: true,
    });
  } catch (error) {
    showToast(error.message);
    return false;
  }
}

function selectedContextPayload() {
  const filters = currentFilters({ preserveScope: true });
  const selectedProjects = Array.from(state.selectedProjectIds)
    .map((projectId) => state.projectLookup.get(projectId))
    .filter(Boolean);
  return {
    cwd: filters.rawCwd,
    project_group: filters.project_group,
    query: refs.queryInput.value.trim(),
    limit: Number(filters.limit || 8),
    project_cwds: selectedProjects.map((project) => project.primary_cwd).filter(Boolean),
    project_names: selectedProjects.map((project) => project.name || project.primary_cwd || "Project"),
    session_ids: Array.from(state.selectedSessionIds),
    file_paths: Array.from(state.selectedFiles.values()).map((asset) => asset.path),
  };
}

function scheduleSelectedStartupContextSync() {
  if (!state.bootstrap) {
    return;
  }
  window.clearTimeout(state.selectedContextSyncTimer);
  state.selectedContextSyncTimer = window.setTimeout(() => {
    void syncSelectedStartupContext();
  }, 350);
}

async function syncSelectedStartupContext({ clear = false, force = false } = {}) {
  if (!state.bootstrap) {
    return;
  }
  const selectedCount = state.selectedSessionIds.size + state.selectedFiles.size;
  const selectedProjectCount = state.selectedProjectIds.size;
  const shouldClear = clear || (selectedCount + selectedProjectCount) === 0;
  if (force && (selectedCount + selectedProjectCount) === 0) {
    showToast("Select projects, memory rows, or files first.");
    return;
  }
  try {
    const payload = shouldClear
      ? { clear: true, enabled: false }
      : { ...selectedContextPayload(), enabled: true };
    const result = await fetchJson("/api/selected-startup-context", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.selectedContextStatus = result.selected_context || null;
    state.selectedContextClearToken = selectedContextClearToken(state.selectedContextStatus) || state.selectedContextClearToken;
    if (shouldClear) {
      state.startupContextEnabled = false;
      updateStartupUI();
    }
    renderSelectedContextStatus(state.selectedContextStatus);
    if (force) {
      showToast(shouldClear ? "Agent startup context cleared." : "Agent startup context armed.");
    }
  } catch (error) {
    showToast(error.message);
  }
}

function clearDashboardStartupSelection(signal) {
  window.clearTimeout(state.selectedContextSyncTimer);
  state.selectedSessionIds.clear();
  state.selectedProjectIds.clear();
  state.selectedFiles.clear();
  state.autoSelectedSessionIds.clear();
  state.startupContextEnabled = false;
  refs.handoffPanel.hidden = true;
  updateStartupUI();
  updateSelectionUI();
  renderSessionRows(state.currentResults);
  renderProjectRows(state.projects);
  renderAssetRows();
  void saveDashboardSettings();
  const reason = signal?.reason === "consumed"
    ? "Startup context was used by a new thread. Selection cleared."
    : "Startup context was reset for a new thread.";
  showToast(reason);
}

function selectedContextClearToken(status) {
  return String(status?.clear_signal?.token || status?.clear_signal?.cleared_at || "");
}

function renderSelectedContextStatus(status) {
  const selectedCount = state.selectedProjectIds.size + state.selectedSessionIds.size + state.selectedFiles.size;
  refs.armSelectedContextButton.disabled = selectedCount === 0;
  if (!status?.exists) {
    refs.selectedContextStatusText.textContent = selectedCount
      ? "Agent startup sync pending"
      : "Agent startup not armed";
    refs.selectedContextStatusText.classList.remove("is-armed");
    return;
  }
  const age = Number(status.age_seconds || 0);
  const ageText = age < 60 ? "just now" : `${Math.floor(age / 60)}m ago`;
  refs.selectedContextStatusText.textContent = `Agent startup armed ${ageText}`;
  refs.selectedContextStatusText.classList.add("is-armed");
}


function formatDate(value) {
  if (!value) {
    return "Unknown date";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(parsed);
}

function formatNumber(value) {
  return new Intl.NumberFormat().format(Number(value || 0));
}

function formatRelativeDate(value) {
  if (!value) {
    return "";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  const diffMs = Date.now() - parsed.getTime();
  const minutes = Math.max(0, Math.floor(diffMs / 60000));
  if (minutes < 60) {
    return `${minutes || 1}m`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours}h`;
  }
  const days = Math.floor(hours / 24);
  if (days < 14) {
    return `${days}d`;
  }
  return `${Math.floor(days / 7)}w`;
}

function shortenPath(value) {
  if (!value) {
    return "";
  }
  const parts = value.split(/[/\\]/).filter(Boolean);
  return parts.length <= 3 ? value : `.../${parts.slice(-3).join("/")}`;
}

async function copyToClipboard(value, successMessage, options = {}) {
  const text = String(value || "");
  const title = options.title || "Text ready";
  if (!text) {
    showToast("Nothing to copy.");
    return false;
  }

  let copied = false;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      copied = true;
    }
  } catch {
    copied = false;
  }

  if (!copied) {
    try {
      const result = await fetchJson("/api/clipboard", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      copied = Boolean(result.ok);
    } catch {
      copied = false;
    }
  }

  if (options.reveal || !copied) {
    showHandoff(text, title);
  }

  showToast(copied ? successMessage : "Clipboard blocked. Use the handoff text box.");
  return copied;
}

function showHandoff(value, title) {
  refs.handoffTitle.textContent = title;
  refs.handoffText.value = String(value || "");
  refs.handoffPanel.hidden = false;
  window.requestAnimationFrame(() => {
    selectHandoffText();
  });
}

function selectHandoffText() {
  refs.handoffText.focus({ preventScroll: true });
  refs.handoffText.select();
}

function showToast(message) {
  refs.toast.textContent = message;
  refs.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    refs.toast.hidden = true;
  }, 2600);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("`", "&#96;");
}
