/**
 * IxNetwork Session Explorer — Application Logic
 *
 * Depends on: config.js (must be loaded first, defines API_BASE_URL)
 *
 * State:
 *   _sessions  — raw data from last successful /sessions fetch
 *   _autoTimer — setInterval handle when auto-refresh is active
 *   _tagTarget — session object currently targeted by the tag modal
 *   _killTarget — session object currently targeted by the kill modal
 */

"use strict";

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------
let _sessions   = null;   // {servers: [...]} from GET /sessions
let _autoTimer  = null;   // setInterval handle
let _tagTarget  = null;   // session targeted by tag modal
let _killTarget = null;   // session targeted by kill modal

// Keyed by `${ixnet_server}/${id}` — populated on each renderServers() call.
// Allows event-delegated button handlers to retrieve the full session object
// without embedding serialized JSON in HTML attributes (XSS mitigation).
const _sessionCache = new Map();

const AUTO_REFRESH_INTERVAL_MS = 30_000;

// ---------------------------------------------------------------------------
// Event delegation — session action buttons
// ---------------------------------------------------------------------------
// A single listener on the static container handles Details / Tag / Kill for
// every dynamically rendered session row.  Session data comes from
// _sessionCache (populated by buildSessionTable) — no JSON in the DOM.

document.getElementById("servers-container").addEventListener("click", e => {
  const btn = e.target.closest(".btn-action");
  if (!btn) return;

  const { action, sessionId, server } = btn.dataset;
  const session = _sessionCache.get(`${server}/${sessionId}`);
  if (!session) {
    console.warn(`btn-action: session not found in cache for key "${server}/${sessionId}"`);
    return;
  }

  if (action === "details") showDetailsModal(session);
  else if (action === "tag")  showTagModal(session);
  else if (action === "kill") showKillConfirm(session);
});

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

/**
 * fetchSessions — GET /sessions, store result, re-render.
 *
 * Expected response shape:
 * {
 *   "status": "ok",
 *   "data": {
 *     "servers": [
 *       {
 *         "name": "ixnet-server-01",
 *         "host": "10.1.1.100",
 *         "sessions": [
 *           {
 *             "id": "1",
 *             "name": "bgp-01",
 *             "chassis": "lab-01",
 *             "ports": ["1/1", "1/2"],
 *             "cp_active": true,
 *             "dp_active": true,
 *             "utilized": true,
 *             "tags": ["bgp"]
 *           }
 *         ]
 *       }
 *     ]
 *   },
 *   "timestamp": "2026-05-08T12:34:56Z"
 * }
 */
async function fetchSessions() {
  setRefreshButtonState(true);
  showLoading();

  try {
    const resp = await fetch(`${API_BASE_URL}/sessions`, {
      headers: { "Accept": "application/json" },
    });

    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
    }

    const body = await resp.json();

    // Support both envelope format { status, data, timestamp } and flat { servers, timestamp }.
    let servers;
    let timestamp;

    if (body.status !== undefined) {
      // Envelope format (production API)
      if (body.status !== "ok") {
        throw new Error(`API error: ${body.error ?? "unknown"}`);
      }
      servers   = (body.data ?? {}).servers ?? [];
      timestamp = body.timestamp ?? body.data?.timestamp ?? new Date().toISOString();
    } else {
      // Flat format (task spec / dev mock)
      servers   = body.servers ?? [];
      timestamp = body.timestamp ?? new Date().toISOString();
    }

    _sessions = { servers };
    updatePollTimestamp(timestamp);
    renderServers(servers);

  } catch (err) {
    showError(`Failed to fetch sessions: ${err.message}`);
  } finally {
    setRefreshButtonState(false);
  }
}

/**
 * triggerRefresh — POST /poll/trigger to force a server-side poll,
 * then re-fetch sessions.
 */
async function triggerRefresh() {
  const btn = document.getElementById("btn-refresh");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Refreshing…";
  }

  try {
    const resp = await fetch(`${API_BASE_URL}/poll/trigger`, {
      method: "POST",
      headers: { "Accept": "application/json" },
    });

    if (!resp.ok) {
      const msg = `Poll trigger failed (HTTP ${resp.status}) — fetching cached state`;
      console.warn(`POST /poll/trigger returned ${resp.status} — falling back to direct fetch`);
      showToast(msg, "error");
    }
  } catch (err) {
    const msg = `Poll trigger unreachable — fetching cached state`;
    console.warn(`POST /poll/trigger failed: ${err.message} — falling back to direct fetch`);
    showToast(msg, "error");
  } finally {
    await fetchSessions();
    if (btn) {
      btn.disabled = false;
      btn.textContent = "↺ Refresh Now";
    }
  }
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

/**
 * renderServers — build server accordion blocks from the servers array.
 *
 * @param {Array} servers  — array of server objects from GET /sessions
 */
function renderServers(servers) {
  const container = document.getElementById("servers-container");

  // Clear stale cache before each full render so removed sessions don't linger.
  _sessionCache.clear();

  if (!servers || servers.length === 0) {
    container.innerHTML = `<div class="state-empty">No IxNetwork servers configured.</div>`;
    return;
  }

  container.innerHTML = "";
  servers.forEach(server => {
    const block = buildServerBlock(server);
    container.appendChild(block);
  });

  // Re-apply active search filter after re-render (preserves filter state).
  const query = document.getElementById("search-input").value.trim();
  if (query) filterServers(query);
}

/**
 * buildServerBlock — create the DOM element for one server accordion.
 *
 * @param {Object} server — { name, host, sessions: [...] }
 * @returns {HTMLElement}
 */
function buildServerBlock(server) {
  const block = document.createElement("div");
  block.className = "server-block";
  block.dataset.serverName = server.name;

  // Prefer server.session_count from API; fall back to sessions array length.
  const sessionCount = server.session_count ?? (server.sessions ?? []).length;

  block.innerHTML = `
    <div class="server-header" role="button" tabindex="0"
         aria-expanded="true" aria-controls="sessions-${sanitizeId(server.name)}">
      <span class="server-toggle-icon" aria-hidden="true">&#9660;</span>
      <span class="server-name">${escapeHtml(server.name)}</span>
      <span class="server-host">(${escapeHtml(server.host)})</span>
      <span class="server-session-count">${sessionCount} session${sessionCount !== 1 ? "s" : ""}</span>
    </div>
    <div class="server-sessions" id="sessions-${sanitizeId(server.name)}">
      ${buildSessionTable(server.sessions ?? [], server.name)}
    </div>
  `;

  // Toggle collapse on header click or keyboard
  const header = block.querySelector(".server-header");
  header.addEventListener("click", () => toggleServerBlock(block));
  header.addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      toggleServerBlock(block);
    }
  });

  return block;
}

/**
 * buildSessionTable — render the <table> for a server's sessions.
 *
 * Populates _sessionCache keyed by `${ixnet_server}/${id}` so that the
 * event-delegation handler in renderServers can retrieve full session objects
 * without any serialized JSON in the HTML.
 *
 * @param {Array}  sessions   — array of session objects
 * @param {string} serverName — canonical server name (from server.name)
 * @returns {string} HTML string
 */
function buildSessionTable(sessions, serverName) {
  if (sessions.length === 0) {
    return `<div class="state-empty" style="padding:20px 16px;">No sessions on this server.</div>`;
  }

  const rows = sessions.map(s => {
    // Ensure ixnet_server is set on the session object (may come from parent).
    const session = s.ixnet_server ? s : { ...s, ixnet_server: serverName };
    _sessionCache.set(`${session.ixnet_server}/${session.id}`, session);
    return renderSessionRow(session);
  }).join("");

  return `
    <table class="sessions-table">
      <thead>
        <tr>
          <th class="col-session">SESSION</th>
          <th class="col-chassis">CHASSIS</th>
          <th class="col-ports">PORTS</th>
          <th class="col-cp">CP</th>
          <th class="col-dp">DP</th>
          <th class="col-utilized">UTILIZED</th>
          <th class="col-actions">ACTIONS</th>
        </tr>
      </thead>
      <tbody>
        ${rows}
      </tbody>
    </table>
  `;
}

/**
 * renderSessionRow — render a single <tr> for one session.
 *
 * Buttons use data-action / data-session-id / data-server attributes.
 * No inline event handlers or serialized JSON appear in the HTML — the full
 * session object is retrieved from _sessionCache by the delegated listener on
 * #servers-container.
 *
 * @param {Object} session — { id, ixnet_server, name, chassis, ports, cp_active, dp_active, utilized, tags }
 * @returns {string} HTML string
 */
function renderSessionRow(session) {
  const cpIcon   = statusIcon(session.cp_active);
  const dpIcon   = statusIcon(session.dp_active);
  const utlClass = session.utilized ? "yes" : "no";
  const utlIcon  = session.utilized ? "&#10003;" : "&#10007;";

  const portsDisplay = Array.isArray(session.ports)
    ? session.ports.join(", ")
    : (session.ports ?? "—");

  const tagsHtml = (session.tags ?? []).length > 0
    ? `<div class="tag-list">${session.tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join("")}</div>`
    : "";

  const sid    = escapeHtml(String(session.id));
  const server = escapeHtml(session.ixnet_server ?? "");

  return `
    <tr data-session-id="${sid}" data-server="${server}">
      <td class="col-session">
        <span class="session-name">${escapeHtml(session.name)}</span>
        ${tagsHtml}
      </td>
      <td class="col-chassis">${escapeHtml(Array.isArray(session.chassis) ? session.chassis.join(", ") : (session.chassis ?? "—"))}</td>
      <td class="col-ports ports-cell">${escapeHtml(portsDisplay)}</td>
      <td class="col-cp">${cpIcon}</td>
      <td class="col-dp">${dpIcon}</td>
      <td class="col-utilized">
        <span class="status-utilized ${utlClass}" aria-label="${session.utilized ? "Utilized" : "Idle"}">
          ${utlIcon}
        </span>
      </td>
      <td class="col-actions">
        <div class="actions-cell">
          <button class="btn btn-details btn-action"
                  data-action="details"
                  data-session-id="${sid}"
                  data-server="${server}">Details</button>
          <button class="btn btn-tag btn-action"
                  data-action="tag"
                  data-session-id="${sid}"
                  data-server="${server}">Tag</button>
          <button class="btn btn-kill btn-action"
                  data-action="kill"
                  data-session-id="${sid}"
                  data-server="${server}">Kill</button>
        </div>
      </td>
    </tr>
  `;
}

// ---------------------------------------------------------------------------
// Filtering
// ---------------------------------------------------------------------------

/**
 * filterServers — show/hide rendered server blocks based on a search query.
 *
 * Operates directly on the DOM via display:none so that no re-render is
 * required on each keystroke.  Matches against server name and server host.
 * If query is empty all blocks are shown.
 *
 * @param {string} query — raw (un-lowercased) search string from the input
 */
function filterServers(query) {
  const normalized = query.trim().toLowerCase();

  document.querySelectorAll(".server-block").forEach(block => {
    if (!normalized) {
      block.style.display = "";
      return;
    }

    const name = (block.dataset.serverName ?? "").toLowerCase();
    // Also match against the host text inside the header (rendered as text content).
    const hostEl = block.querySelector(".server-host");
    const host   = hostEl ? hostEl.textContent.replace(/[()]/g, "").trim().toLowerCase() : "";

    const matches = name.includes(normalized) || host.includes(normalized);
    block.style.display = matches ? "" : "none";
  });
}

// ---------------------------------------------------------------------------
// Expand / Collapse
// ---------------------------------------------------------------------------

function toggleServerBlock(block) {
  const isCollapsed = block.classList.contains("collapsed");
  block.classList.toggle("collapsed", !isCollapsed);
  const header = block.querySelector(".server-header");
  header.setAttribute("aria-expanded", isCollapsed ? "true" : "false");
}

function expandAll() {
  document.querySelectorAll(".server-block").forEach(b => {
    b.classList.remove("collapsed");
    b.querySelector(".server-header").setAttribute("aria-expanded", "true");
  });
}

function collapseAll() {
  document.querySelectorAll(".server-block").forEach(b => {
    b.classList.add("collapsed");
    b.querySelector(".server-header").setAttribute("aria-expanded", "false");
  });
}

// ---------------------------------------------------------------------------
// Auto-refresh
// ---------------------------------------------------------------------------

/**
 * toggleAutoRefresh — start or stop the 30-second auto-refresh interval.
 */
function toggleAutoRefresh() {
  const btn = document.getElementById("btn-auto-refresh");

  if (_autoTimer) {
    // Turning OFF: clear interval first, then null the handle
    clearInterval(_autoTimer);
    _autoTimer = null;
    btn.textContent = "Auto-refresh: OFF";
    btn.classList.remove("active");
    btn.setAttribute("aria-pressed", "false");
  } else {
    // Turning ON
    _autoTimer = setInterval(fetchSessions, AUTO_REFRESH_INTERVAL_MS);
    btn.textContent = "Auto-refresh: ON";
    btn.classList.add("active");
    btn.setAttribute("aria-pressed", "true");
  }
}

// ---------------------------------------------------------------------------
// Modals
// ---------------------------------------------------------------------------

/**
 * showDetailsModal — display full session detail in the details modal.
 *
 * @param {Object} session — session object from _sessionCache
 */
function showDetailsModal(session) {
  const body = document.getElementById("modal-details-body");

  const portsDisplay = Array.isArray(session.ports)
    ? session.ports.join(", ")
    : (session.ports ?? "—");

  const chassisDisplay = Array.isArray(session.chassis)
    ? session.chassis.join(", ")
    : (session.chassis ?? "—");

  const tagsDisplay = (session.tags ?? []).length > 0
    ? session.tags.join(", ")
    : "None";

  // Returns an HTML snippet — safe to embed directly (no user data, only fixed glyphs).
  const boolCell = val => val
    ? `<span class="detail-ok">&#10003;</span>`
    : `<span class="detail-err">&#10007;</span>`;

  let lastPolledDisplay = "—";
  if (session.last_polled) {
    try {
      const d = new Date(session.last_polled);
      lastPolledDisplay = isNaN(d.getTime())
        ? escapeHtml(String(session.last_polled))
        : d.toLocaleString();
    } catch {
      lastPolledDisplay = escapeHtml(String(session.last_polled));
    }
  }

  body.innerHTML = `
    <dl>
      <dt>Session ID</dt>   <dd>${escapeHtml(String(session.id ?? "—"))}</dd>
      <dt>Name</dt>         <dd>${escapeHtml(session.name ?? "—")}</dd>
      <dt>Server</dt>       <dd>${escapeHtml(session.ixnet_server ?? "—")}</dd>
      <dt>Chassis</dt>      <dd>${escapeHtml(chassisDisplay)}</dd>
      <dt>Ports</dt>        <dd>${escapeHtml(portsDisplay)}</dd>
      <dt>CP Active</dt>    <dd>${boolCell(session.cp_active)}</dd>
      <dt>DP Active</dt>    <dd>${boolCell(session.dp_active)}</dd>
      <dt>Utilized</dt>     <dd>${boolCell(session.utilized)}</dd>
      <dt>Tags</dt>         <dd>${escapeHtml(tagsDisplay)}</dd>
      <dt>Last Polled</dt>  <dd>${lastPolledDisplay}</dd>
    </dl>
  `;

  openModal("modal-details");
}

/**
 * showTagModal — display the tag-addition modal for a session.
 *
 * @param {Object} session — session object from _sessionCache
 */
function showTagModal(session) {
  _tagTarget = session;

  document.getElementById("modal-tag-session-name").textContent = session.name ?? session.id;

  const existingContainer = document.getElementById("modal-tag-existing");
  existingContainer.innerHTML = (session.tags ?? []).length > 0
    ? session.tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join("")
    : `<span style="font-size:0.78rem; color:var(--color-text-dim);">No existing tags.</span>`;

  document.getElementById("tag-input-field").value = "";

  // Reset error state from previous open
  const errEl = document.getElementById("modal-tag-error");
  errEl.textContent = "";
  errEl.style.display = "none";

  openModal("modal-tag");
  document.getElementById("tag-input-field").focus();
}

/**
 * showKillConfirm — display the kill-confirmation modal.
 *
 * @param {Object} session — session object from _sessionCache
 */
function showKillConfirm(session) {
  _killTarget = session;

  const name   = session.name ?? session.id;
  const server = session.ixnet_server ?? "unknown";

  const descEl = document.getElementById("modal-kill-description");
  // Use textContent to avoid XSS; the element is a plain <p>.
  descEl.textContent = `Kill session '${name}' on ${server}?`;

  // Reset button and error state from previous open
  const killBtn = document.getElementById("btn-kill-confirm");
  killBtn.disabled = false;
  killBtn.textContent = "Kill Session";

  const errEl = document.getElementById("modal-kill-error");
  errEl.textContent = "";
  errEl.style.display = "none";

  openModal("modal-kill");
}

/**
 * submitTag — PATCH /sessions/{server}/{id}/tags with add or remove action.
 *
 * @param {"add"|"remove"} action
 */
async function submitTag(action) {
  if (!_tagTarget) return;

  const tag = document.getElementById("tag-input-field").value.trim();

  const errEl = document.getElementById("modal-tag-error");
  errEl.textContent = "";
  errEl.style.display = "none";

  if (!tag) {
    errEl.textContent = "Tag name cannot be empty.";
    errEl.style.display = "block";
    document.getElementById("tag-input-field").focus();
    return;
  }

  const addBtn    = document.getElementById("btn-tag-add");
  const removeBtn = document.getElementById("btn-tag-remove");
  const isAdd     = action === "add";

  // Loading state
  addBtn.disabled    = true;
  removeBtn.disabled = true;
  addBtn.textContent    = isAdd ? "Adding…" : "Add Tag";
  removeBtn.textContent = isAdd ? "Remove Tag" : "Removing…";

  const { ixnet_server, id } = _tagTarget;
  const url = `${API_BASE_URL}/sessions/${encodeURIComponent(ixnet_server)}/${encodeURIComponent(id)}/tags`;

  try {
    const resp = await fetch(url, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "Accept":        "application/json",
      },
      body: JSON.stringify({ action, tag }),
    });

    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`;
      try {
        const body = await resp.json();
        detail = body.error ?? body.detail ?? detail;
      } catch { /* ignore parse error — use status text */ }
      throw new Error(detail);
    }

    const verb = isAdd ? "added to" : "removed from";
    showToast(`Tag "${tag}" ${verb} session "${_tagTarget.name ?? _tagTarget.id}"`, "ok");
    closeModal("modal-tag");
    _tagTarget = null;
    await fetchSessions();

  } catch (err) {
    errEl.textContent = `Error: ${err.message}`;
    errEl.style.display = "block";
  } finally {
    addBtn.disabled    = false;
    removeBtn.disabled = false;
    addBtn.textContent    = "Add Tag";
    removeBtn.textContent = "Remove Tag";
  }
}

/**
 * confirmKill — DELETE /sessions/{server}/{id}?confirm=true
 */
async function confirmKill() {
  if (!_killTarget) return;

  const killBtn = document.getElementById("btn-kill-confirm");
  const errEl   = document.getElementById("modal-kill-error");

  errEl.textContent = "";
  errEl.style.display = "none";

  // Loading state
  killBtn.disabled    = true;
  killBtn.textContent = "Killing…";

  const { ixnet_server, id, name } = _killTarget;
  const url = `${API_BASE_URL}/sessions/${encodeURIComponent(ixnet_server)}/${encodeURIComponent(id)}?confirm=true`;

  try {
    const resp = await fetch(url, {
      method: "DELETE",
      headers: { "Accept": "application/json" },
    });

    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`;
      try {
        const body = await resp.json();
        detail = body.error ?? body.detail ?? detail;
      } catch { /* ignore parse error */ }
      throw new Error(detail);
    }

    showToast(`Session "${name ?? id}" killed successfully.`, "ok");
    closeModal("modal-kill");
    _killTarget = null;
    await fetchSessions();

  } catch (err) {
    errEl.textContent = `Error: ${err.message}`;
    errEl.style.display = "block";
    // Restore button so user can retry or cancel
    killBtn.disabled    = false;
    killBtn.textContent = "Kill Session";
  }
}

// ---------------------------------------------------------------------------
// Modal helpers
// ---------------------------------------------------------------------------

function openModal(id) {
  const overlay = document.getElementById(id);
  if (overlay) {
    overlay.classList.add("visible");
    // Trap focus on first focusable element
    const focusable = overlay.querySelector("button, input, [tabindex]");
    if (focusable) focusable.focus();
  }
}

function closeModal(id) {
  const overlay = document.getElementById(id);
  if (overlay) overlay.classList.remove("visible");
}

// Close modal on overlay click
document.querySelectorAll(".modal-overlay").forEach(overlay => {
  overlay.addEventListener("click", e => {
    if (e.target === overlay) closeModal(overlay.id);
  });
});

// Escape key closes all open modals
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    document.querySelectorAll(".modal-overlay.visible").forEach(m => {
      closeModal(m.id);
    });
  }
});

// ----- Close buttons (.modal-close) ------------------------------------
document.querySelectorAll(".modal-close").forEach(btn => {
  btn.addEventListener("click", () => {
    const target = btn.dataset.modal;
    if (target) closeModal(target);
  });
});

// ----- Tag submit -------------------------------------------------------
document.getElementById("btn-tag-add").addEventListener("click", () => submitTag("add"));
document.getElementById("btn-tag-remove").addEventListener("click", () => submitTag("remove"));
document.getElementById("tag-input-field").addEventListener("keydown", e => {
  if (e.key === "Enter") submitTag("add");
});

// ----- Kill confirm -----------------------------------------------------
document.getElementById("btn-kill-confirm").addEventListener("click", confirmKill);

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

function updatePollTimestamp(isoString) {
  const el = document.getElementById("poll-timestamp");
  if (!el) return;

  if (!isoString) {
    el.textContent = "Never";
    return;
  }

  try {
    const d = new Date(isoString);
    // new Date() on an invalid string produces NaN for getTime()
    if (isNaN(d.getTime())) {
      el.textContent = "Never";
      return;
    }
    el.textContent = d.toLocaleString();
  } catch {
    el.textContent = "Never";
  }
}

function setRefreshButtonState(loading) {
  const btn = document.getElementById("btn-refresh");
  if (!btn) return;
  btn.disabled = loading;
  btn.textContent = loading ? "Refreshing…" : "↺ Refresh Now";
}

function statusIcon(active) {
  return active
    ? `<span class="status-ok" aria-label="Active">&#10003;</span>`
    : `<span class="status-err" aria-label="Inactive">&#10007;</span>`;
}

function showLoading() {
  const container = document.getElementById("servers-container");
  container.innerHTML = `<div class="state-loading"><span class="spinner"></span> Loading sessions…</div>`;
}

function showError(message) {
  const container = document.getElementById("servers-container");
  container.innerHTML = `<div class="state-error">${escapeHtml(message)}</div>`;
  showToast(message, "error");
}

function showToast(message, type = "ok") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 5000);
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function sanitizeId(str) {
  return String(str).replace(/[^a-zA-Z0-9_-]/g, "_");
}

// ---------------------------------------------------------------------------
// Event listeners — controls
// ---------------------------------------------------------------------------

document.getElementById("btn-refresh").addEventListener("click", triggerRefresh);

document.getElementById("btn-expand-all").addEventListener("click", expandAll);
document.getElementById("btn-collapse-all").addEventListener("click", collapseAll);

document.getElementById("btn-auto-refresh").addEventListener("click", toggleAutoRefresh);

document.getElementById("search-input").addEventListener("input", e => {
  filterServers(e.target.value);
});

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------
fetchSessions();
