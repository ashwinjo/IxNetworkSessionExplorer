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

  if (action === "tag")        showTagModal(session);
  else if (action === "kill")  showKillConfirm(session);
  else if (action === "logs")  collectLogs(session, btn);
  else if (action === "errors") showErrorsModal(session);
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
    const resp = await fetch(`${API_BASE_URL}/sessions/`, {
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
 * waitForPollComplete — polls GET /poll/status until is_polling is false.
 * Gives up after maxWaitMs (default 30s) to avoid hanging forever.
 */
async function waitForPollComplete(maxWaitMs = 30_000) {
  const interval = 500;
  const deadline = Date.now() + maxWaitMs;
  while (Date.now() < deadline) {
    try {
      const resp = await fetch(`${API_BASE_URL}/poll/status`, {
        headers: { "Accept": "application/json" },
      });
      if (resp.ok) {
        const data = await resp.json();
        if (!data.is_polling) return;
      }
    } catch (_) {
      // network hiccup — keep waiting
    }
    await new Promise(resolve => setTimeout(resolve, interval));
  }
}

/**
 * triggerRefresh — POST /poll/trigger to force a server-side poll,
 * waits for the poll to finish, then re-fetches sessions.
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
    } else {
      // Wait for the background poll cycle to complete before fetching
      await waitForPollComplete();
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

/**
 * IxNetwork Web panel (from GET /sessions server row).
 *
 * @param {string|undefined|null} d          ixnetwork_web_deployment
 * @param {string|undefined|null} h          ixnetwork_web_heartbeat
 * @param {string|undefined|null} checkedAt  ixnetwork_web_checked_at ISO string
 * @returns {string}
 */
function formatIxWebDeployment(d, h, checkedAt) {
  if (d === "standalone") return "Standalone";
  if (d === "onChassis")  return "On Chassis";
  if (h === "red")        return "Unreachable";
  // yellow: distinguish "never run" from "ran but auth failed"
  if (h === "yellow")     return checkedAt ? "Auth Failed" : "Not Probed";
  return "—";
}

/**
 * CSS classes for deployment pill (standalone vs on-chassis vs unknown).
 *
 * @param {string|undefined|null} d          ixnetwork_web_deployment
 * @param {string|undefined|null} h          ixnetwork_web_heartbeat
 * @param {string|undefined|null} checkedAt  ixnetwork_web_checked_at
 * @returns {string}
 */
function ixWebDeploymentClass(d, h, checkedAt) {
  if (d === "standalone") return "server-web-deployment server-web-deployment--standalone";
  if (d === "onChassis")  return "server-web-deployment server-web-deployment--on-chassis";
  if (h === "red")        return "server-web-deployment server-web-deployment--unreachable";
  if (h === "yellow" && checkedAt) return "server-web-deployment server-web-deployment--auth-failed";
  return "server-web-deployment server-web-deployment--unknown";
}

/**
 * @param {string|undefined|null} h  ixnetwork_web_heartbeat
 */
function ixWebHeartbeatClass(h) {
  if (h === "green") return "server-heartbeat server-heartbeat--green";
  if (h === "red") return "server-heartbeat server-heartbeat--red";
  return "server-heartbeat server-heartbeat--yellow";
}

/**
 * buildIxWebConsoleUrl — construct the IxNetwork Web Console login URL.
 *
 * Port 443 is the HTTPS default and is omitted from the URL per the spec.
 *
 * @param {string} host       — server IP or hostname
 * @param {number|null} port  — REST port (null / undefined treated as 443)
 * @returns {string}
 */
function buildIxWebConsoleUrl(host, port) {
  const p = port ? parseInt(port, 10) : 443;
  const portStr = (p === 443) ? "" : `:${p}`;
  return `https://${host}${portStr}/ixnetworkweb/login`;
}

/**
 * @param {Object} server
 */
function ixWebHeartbeatTitle(server) {
  const h = server.ixnetwork_web_heartbeat ?? "yellow";
  const d = server.ixnetwork_web_deployment;
  const detail = server.ixnetwork_web_detail;
  const checkedAt = server.ixnetwork_web_checked_at;
  const lines = [];

  if (h === "green") {
    const depStr = d === "standalone"
      ? "standalone VM"
      : d === "onChassis"
        ? "on-chassis"
        : "deployment unknown";
    lines.push(`IxNetwork Web: reachable · ${depStr} · HTTPS auth OK`);
  } else if (h === "red") {
    lines.push("IxNetwork Web: unreachable — network error on both auth paths.");
  } else {
    // yellow: either not yet probed, or auth responded but no API key
    if (!checkedAt) {
      lines.push("IxNetwork Web: not yet probed — trigger a refresh.");
    } else {
      lines.push("IxNetwork Web: degraded — HTTPS auth did not return an API key.");
    }
  }

  if (detail) lines.push(detail);
  if (checkedAt) {
    try {
      lines.push(`Last checked: ${new Date(checkedAt).toLocaleString()}`);
    } catch { /* ignore */ }
  }
  return lines.join("\n");
}


/**
 * renderServers — build server accordion blocks from the servers array.
 *
 * @param {Array} servers  — array of server objects from GET /sessions
 */
function updateStats(servers) {
  const totalSessions   = servers.reduce((a, s) => a + (s.session_count ?? (s.sessions ?? []).length), 0);
  const activeSessions  = servers.reduce((a, s) => a + (s.sessions ?? []).filter(sess => sess.cp_active || sess.dp_active).length, 0);
  const utilizedSessions = servers.reduce((a, s) => a + (s.sessions ?? []).filter(sess => sess.utilized).length, 0);
  const errorSessions   = servers.reduce((a, s) => a + (s.sessions ?? []).filter(sess => sess.error_status === "ERROR").length, 0);
  const serversOnline   = servers.filter(s => !s.poll_error).length;

  const el = id => document.getElementById(id);
  el("stat-servers").textContent        = servers.length;
  el("stat-sessions").textContent       = totalSessions;
  el("stat-active").textContent         = activeSessions;
  el("stat-utilized").textContent       = utilizedSessions;
  el("stat-servers-online").textContent = `${serversOnline}/${servers.length}`;

  const errEl = el("stat-errors");
  errEl.textContent = errorSessions;
  errEl.classList.toggle("has-errors", errorSessions > 0);
}

function renderServers(servers) {
  const container = document.getElementById("servers-container");

  // Snapshot which server blocks are currently expanded so we can restore
  // the same open/closed state after the DOM is rebuilt.
  const expandedNames = new Set(
    [...document.querySelectorAll(".server-block:not(.collapsed)")]
      .map(b => b.dataset.serverName)
  );

  // Clear stale cache before each full render so removed sessions don't linger.
  _sessionCache.clear();

  updateStats(servers ?? []);

  if (!servers || servers.length === 0) {
    container.innerHTML = `<div class="state-empty">No IxNetwork servers configured.</div>`;
    return;
  }

  container.innerHTML = "";
  servers.forEach(server => {
    const block = buildServerBlock(server);
    // Restore expanded state from before the re-render
    if (expandedNames.has(server.name)) {
      block.classList.remove("collapsed");
      block.querySelector(".server-header").setAttribute("aria-expanded", "true");
    }
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
  block.className = "server-block collapsed";
  block.dataset.serverName = server.name;

  // Prefer server.session_count from API; fall back to sessions array length.
  const sessionCount = server.session_count ?? (server.sessions ?? []).length;

  const hb        = server.ixnetwork_web_heartbeat ?? "yellow";
  const dep       = server.ixnetwork_web_deployment ?? null;
  const checkedAt = server.ixnetwork_web_checked_at ?? null;
  const ixVersion = server.ixnetwork_version ?? null;
  const hbTitle   = escapeHtml(ixWebHeartbeatTitle(server));
  const depLabel  = escapeHtml(formatIxWebDeployment(dep, hb, checkedAt));
  const depTitle  = dep === "standalone"
    ? "Standalone VM — IxNetwork Web on dedicated server"
    : dep === "onChassis"
      ? "On-Chassis — IxNetwork Web embedded in chassis"
      : hb === "red"
        ? "Unreachable — HTTPS auth probe failed on both paths"
        : checkedAt
          ? "Auth Failed — probe ran but no API key returned (check credentials / password)"
          : "Not yet probed — click Refresh to run the heartbeat probe";
  const versionHtml = ixVersion
    ? `<span class="server-ixn-version" title="IxNetwork (ixnrest) version">v${escapeHtml(ixVersion)}</span>`
    : "";

  const consoleUrl = buildIxWebConsoleUrl(server.host, server.rest_port ?? null);
  const pollError  = server.poll_error ?? null;
  const pollErrorHtml = pollError
    ? `<span class="server-poll-error" title="${escapeHtml(pollError)}">Connection Failed</span>`
    : "";

  block.innerHTML = `
    <div class="server-header" role="button" tabindex="0"
         aria-expanded="false" aria-controls="sessions-${sanitizeId(server.name)}">
      <span class="server-toggle-icon" aria-hidden="true">&#9660;</span>
      <span class="${ixWebHeartbeatClass(hb)}"
            title="${hbTitle}"
            role="img"
            aria-label="IxNetwork Web status: ${escapeHtml(hb)}"></span>
      <span class="server-name">${escapeHtml(server.name)}</span>
      <span class="server-host">(${escapeHtml(server.host)})</span>
      ${pollErrorHtml}
      <span class="${ixWebDeploymentClass(dep, hb, checkedAt)}"
            title="${escapeHtml(depTitle)}">${depLabel}</span>
      ${versionHtml}
      <span class="server-session-count">${sessionCount} session${sessionCount !== 1 ? "s" : ""}</span>
      <a class="btn-ixweb-console"
         href="${escapeHtml(consoleUrl)}"
         target="_blank"
         rel="noopener noreferrer"
         title="Open IxNetwork Web Console: ${escapeHtml(consoleUrl)}">
        <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M6 2H2.5A1.5 1.5 0 001 3.5v8A1.5 1.5 0 002.5 13h8A1.5 1.5 0 0012 11.5V8"/>
          <path d="M8 1h5v5"/>
          <path d="M13 1L6.5 7.5"/>
        </svg>
        Console
      </a>
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

  // Console link must not bubble up and toggle the accordion
  const consoleLink = block.querySelector(".btn-ixweb-console");
  if (consoleLink) {
    consoleLink.addEventListener("click", e => e.stopPropagation());
  }

  return block;
}

/**
 * buildSessionTable — render the <table> for a server's sessions.
 *
 * Each session may span multiple rows — one row per assigned port.
 * Session-level cells (name, CP, DP, UTILIZED, ACTIONS) use rowspan.
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
    const session = s.ixnet_server ? s : { ...s, ixnet_server: serverName };
    _sessionCache.set(`${session.ixnet_server}/${session.id}`, session);
    return renderSessionRows(session);
  }).join("");

  return `
    <table class="sessions-table">
      <thead>
        <tr>
          <th class="col-session">SESSION</th>
          <th class="col-chassis">CHASSIS</th>
          <th class="col-port">PORT</th>
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
 * buildPortCell — render the PORT cell content for a single vport.
 *
 * Shows card/port number, connection-state dot, optional logical name,
 * and an LLDP neighbor line when peer info is available.
 *
 * connection_state values from IxNetwork:
 *   connectedLinkUp | connectedLinkDown | notConnected | unassigned | ""
 *
 * @param {Object} p — SessionPort object
 * @returns {string} HTML string
 */
function buildPortCell(p) {
  const num   = escapeHtml(`${p.card}/${p.port}`);
  const speedLabel = p.actual_speed > 0
    ? (p.actual_speed >= 1000 ? `${p.actual_speed / 1000}G` : `${p.actual_speed}M`)
    : "";
  const speed = speedLabel
    ? ` <span class="vport-name">${speedLabel}</span>`
    : "";
  const state = p.connection_state || "";

  let dotClass = "link-unknown";
  let dotTitle = state || "unknown";
  if (state === "connectedLinkUp")   { dotClass = "link-up";   dotTitle = "Link Up"; }
  else if (state === "connectedLinkDown") { dotClass = "link-down"; dotTitle = "Link Down"; }
  else if (state === "notConnected") { dotClass = "link-none"; dotTitle = "Not Connected"; }
  else if (state === "unassigned")   { dotClass = "link-none"; dotTitle = "Unassigned"; }

  return `<span class="port-num">${num}</span><span class="link-dot ${dotClass}" title="${escapeHtml(dotTitle)}"></span>${speed}`;
}

/**
 * buildDetailsRowHtml — render the inline LLDP details sub-row for a session.
 *
 * Always visible (no toggle required).  Spans all 7 columns of the main table.
 *
 * @param {Object} session — session object with ports array
 * @returns {string} HTML string (<tr class="details-row">)
 */
function buildDetailsRowHtml(session) {
  const MAIN_COL_COUNT = 7;
  const owner = escapeHtml(session.username || session.name || "—");
  const ports = Array.isArray(session.ports) ? session.ports : [];

  const portRows = ports.length > 0
    ? ports.map(p => {
        const chassis = escapeHtml(typeof p === "object" ? (p.chassis_name ?? "—") : String(p));
        const portNum = typeof p === "object" ? escapeHtml(`${p.card}/${p.port}`) : "—";

        let lldpCells = `<td class="lldp-col lldp-none">—</td>
                         <td class="lldp-col lldp-none">—</td>
                         <td class="lldp-col lldp-none">—</td>
                         <td class="lldp-col lldp-none">—</td>`;

        const lldp = typeof p === "object" ? p.lldp_peer : null;
        if (lldp && (lldp.peer_system_name || lldp.peer_chassis_id || lldp.peer_port_id)) {
          lldpCells = `<td class="lldp-col lldp-val">${escapeHtml(lldp.peer_system_name || "—")}</td>
                       <td class="lldp-col lldp-val">${escapeHtml(lldp.peer_port_id || "—")}</td>
                       <td class="lldp-col lldp-val">${escapeHtml(lldp.peer_ip_address || "—")}</td>
                       <td class="lldp-col lldp-val lldp-chassis-id">${escapeHtml(lldp.peer_chassis_id || "—")}</td>`;
        }

        return `<tr><td>${chassis}</td><td>${portNum}</td><td>${owner}</td>${lldpCells}</tr>`;
      }).join("")
    : `<tr><td colspan="7" class="details-empty">No ports assigned</td></tr>`;

  return `
    <tr class="details-row">
      <td colspan="${MAIN_COL_COUNT}" class="details-cell">
        <table class="details-table details-table--lldp">
          <thead>
            <tr>
              <th>CHASSIS</th>
              <th>PORT</th>
              <th>OWNER</th>
              <th class="lldp-col lldp-hdr">LLDP PEER</th>
              <th class="lldp-col lldp-hdr">PEER PORT</th>
              <th class="lldp-col lldp-hdr">PEER IP</th>
              <th class="lldp-col lldp-hdr">PEER CHASSIS ID</th>
            </tr>
          </thead>
          <tbody>${portRows}</tbody>
        </table>
      </td>
    </tr>`;
}

/**
 * renderSessionRows — render one or more <tr> elements for a session.
 *
 * Produces one row per assigned port.  Session-level cells span all port rows
 * via rowspan.  Sessions with no ports produce a single row with "—" for
 * chassis and port.
 *
 * @param {Object} session — { id, ixnet_server, name, ports, cp_active, dp_active, utilized, tags }
 * @returns {string} HTML string (potentially multiple <tr> elements)
 */
function renderSessionRows(session) {
  const tagsHtml = (session.tags ?? []).length > 0
    ? `<div class="tag-list">${session.tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join("")}</div>`
    : "";

  // Session state badge
  const rawState = (session.session_state ?? "").toLowerCase();
  let stateCls = "session-state-badge";
  if (rawState === "active")  stateCls += " state-active";
  else if (rawState === "stopped") stateCls += " state-stopped";
  else if (rawState === "initial") stateCls += " state-initial";
  const stateHtml = session.session_state
    ? `<span class="${stateCls}">${escapeHtml(session.session_state)}</span>`
    : "";

  // Error status pill
  const hasError   = (session.error_status ?? "NOERROR") === "ERROR";
  const errCount   = session.error_count ?? 0;
  const errClass   = hasError ? "error" : "noerror";
  const errLabel   = hasError
    ? `&#10007; ${errCount} Error${errCount !== 1 ? "s" : ""}`
    : "&#10003; NOERROR";
  const errTitle   = hasError
    ? `${errCount} kError-level AppError(s) detected — click to view`
    : "No errors detected";
  const errAction  = hasError ? `data-action="errors"` : "";
  const errBtnClass = hasError
    ? `btn btn-error-status error btn-action`
    : `btn btn-error-status noerror`;

  const sid    = escapeHtml(String(session.id));
  const server = escapeHtml(session.ixnet_server ?? "");

  const ports = Array.isArray(session.ports) && session.ports.length > 0
    ? session.ports
    : [null];  // sentinel: one row with "—"

  const rowspan = ports.length > 1 ? ` rowspan="${ports.length}"` : "";

  // Session-level cells — only emitted on the first row
  const sessionCell = `
    <td class="col-session"${rowspan}>
      <span class="session-name">${escapeHtml(session.name)}</span>
      ${stateHtml}
      ${tagsHtml}
    </td>`;

  const actionsCells = `
    <td class="col-actions"${rowspan}>
      <div class="actions-cell">
        <button class="${errBtnClass}"
                ${errAction}
                data-session-id="${sid}"
                data-server="${server}"
                title="${escapeHtml(errTitle)}">${errLabel}</button>
        <button class="btn btn-tag btn-action"
                data-action="tag"
                data-session-id="${sid}"
                data-server="${server}">Tag</button>
        <button class="btn btn-logs btn-action"
                data-action="logs"
                data-session-id="${sid}"
                data-server="${server}"
                title="Collect and download diagnostic logs">Logs</button>
        <button class="btn btn-kill btn-action"
                data-action="kill"
                data-session-id="${sid}"
                data-server="${server}">Kill</button>
      </div>
    </td>`;

  return ports.map((p, i) => {
    const chassis   = p ? escapeHtml(p.chassis_name ?? "—") : "—";
    const portLabel = p ? buildPortCell(p) : "—";

    // Per-port plane status
    const pCpIcon   = p ? statusIcon(p.cp_active)   : statusIcon(false);
    const pDpIcon   = p ? statusIcon(p.dp_active)   : statusIcon(false);
    const pUtlClass = (p && p.utilized) ? "yes" : "no";
    const pUtlIcon  = (p && p.utilized) ? "&#10003;" : "&#10007;";

    const portStatusCells = `
      <td class="col-cp">${pCpIcon}</td>
      <td class="col-dp">${pDpIcon}</td>
      <td class="col-utilized">
        <span class="status-utilized ${pUtlClass}" aria-label="${(p && p.utilized) ? "Utilized" : "Idle"}">
          ${pUtlIcon}
        </span>
      </td>`;

    const isLast = i === ports.length - 1;

    if (i === 0) {
      return `
        <tr class="session-first-row" data-session-id="${sid}" data-server="${server}">
          ${sessionCell}
          <td class="col-chassis">${chassis}</td>
          <td class="col-port port-cell">${portLabel}</td>
          ${portStatusCells}
          ${actionsCells}
        </tr>${isLast ? buildDetailsRowHtml(session) : ""}`;
    }
    return `
      <tr class="session-port-row" data-session-id="${sid}" data-server="${server}">
        <td class="col-chassis">${chassis}</td>
        <td class="col-port port-cell">${portLabel}</td>
        ${portStatusCells}
      </tr>${isLast ? buildDetailsRowHtml(session) : ""}`;
  }).join("");
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
 * showErrorsModal — display kError-level AppErrors for a session.
 *
 * @param {Object} session — session object from _sessionCache
 */
function showErrorsModal(session) {
  const name     = session.name ?? session.id;
  const errors   = session.error_list ?? [];
  const count    = session.error_count ?? 0;
  const hasError = (session.error_status ?? "NOERROR") === "ERROR";

  const nameEl = document.getElementById("modal-errors-session-name");
  const bodyEl = document.getElementById("modal-errors-body");

  nameEl.textContent = name;

  if (!hasError || errors.length === 0) {
    bodyEl.innerHTML = `
      <div class="error-list-empty">
        <span style="color:var(--green);font-size:1rem;">&#10003;</span>
        No kError-level AppErrors detected on this session.
      </div>`;
  } else {
    const countBadge = `<span class="error-count-badge">${count} total</span>`;
    const items = errors
      .map(e => `<li>${escapeHtml(e)}</li>`)
      .join("");
    bodyEl.innerHTML = `
      <p style="font-size:0.75rem;color:var(--text-dim);margin-bottom:4px;">
        kError-level AppErrors${countBadge}
      </p>
      <ul class="error-list">${items}</ul>`;
  }

  openModal("modal-errors");
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

  const raw = document.getElementById("tag-input-field").value;

  // Split on commas, trim whitespace, drop empty strings — supports multi-tag input
  const tags = raw.split(",").map(t => t.trim()).filter(Boolean);

  const errEl = document.getElementById("modal-tag-error");
  errEl.textContent = "";
  errEl.style.display = "none";

  if (tags.length === 0) {
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

  // Backend expects { add: [...], remove: [...] } — send all tags in one request
  const body = isAdd ? { add: tags, remove: [] } : { add: [], remove: tags };

  try {
    const resp = await fetch(url, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "Accept":        "application/json",
      },
      body: JSON.stringify(body),
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
    const label = tags.length === 1 ? `"${tags[0]}"` : `${tags.length} tags`;
    showToast(`${label} ${verb} session "${_tagTarget.name ?? _tagTarget.id}"`, "ok");
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

/**
 * collectLogs — POST /sessions/{server}/{id}/collect-logs and download the zip.
 *
 * Disables the triggering button while the request is in flight (log collection
 * can take several seconds) and restores it when done, whether or not the
 * request succeeded.
 *
 * @param {Object}      session — session object from _sessionCache
 * @param {HTMLElement} btn     — the button element that was clicked
 */
async function collectLogs(session, btn) {
  const { ixnet_server, id, name } = session;
  const url = `${API_BASE_URL}/sessions/${encodeURIComponent(ixnet_server)}/${encodeURIComponent(id)}/collect-logs`;

  const origText = btn ? btn.textContent : "Logs";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "…";
  }

  showToast(`Collecting logs for "${name ?? id}"…`, "ok");

  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Accept": "application/zip, application/json" },
    });

    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`;
      try {
        const body = await resp.json();
        detail = body.error ?? body.detail ?? detail;
      } catch { /* response was binary, not JSON */ }
      throw new Error(detail);
    }

    // Derive filename from Content-Disposition header if present, else build one.
    let filename = `diagnostic_logs_${name ?? id}.zip`;
    const disposition = resp.headers.get("Content-Disposition");
    if (disposition) {
      const match = disposition.match(/filename[^;=\n]*=["']?([^"'\n;]+)/i);
      if (match) filename = match[1].trim();
    }

    const blob = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = blobUrl;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(blobUrl);

    showToast(`Logs downloaded for "${name ?? id}"`, "ok");

  } catch (err) {
    showToast(`Log collection failed: ${err.message}`, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = origText;
    }
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
// Server Management
// ---------------------------------------------------------------------------

let _serverDeleteTarget = null;  // name of server pending deletion

/**
 * openServerManager — load server list and show the manage modal.
 */
async function openServerManager() {
  openModal("modal-servers");
  await refreshServerList();
}

/**
 * refreshServerList — fetch GET /servers and re-render the list area.
 */
async function refreshServerList() {
  const area = document.getElementById("servers-list-area");
  area.innerHTML = `<div class="state-loading"><span class="spinner"></span> Loading…</div>`;

  try {
    const resp = await fetch(`${API_BASE_URL}/servers/`, {
      headers: { "Accept": "application/json" },
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const body = await resp.json();
    const servers = body.data?.servers ?? [];
    renderServerList(servers);
  } catch (err) {
    area.innerHTML = `<div class="state-error">Failed to load servers: ${escapeHtml(err.message)}</div>`;
  }
}

/**
 * renderServerList — build the server table with checkboxes inside the manage modal.
 */
function renderServerList(servers) {
  const area = document.getElementById("servers-list-area");

  if (servers.length === 0) {
    area.innerHTML = `<div class="server-list-empty">No servers configured yet. Click <strong>Add Server</strong> to get started.</div>`;
    updateBulkBar();
    return;
  }

  const rows = servers.map(s => {
    const eName = escapeHtml(s.name);
    const eHost = escapeHtml(s.host);
    const eUser = escapeHtml(s.username);
    const ePort = s.rest_port ?? "auto";
    // Encode values as data attributes — no inline JS with dynamic strings
    return `
    <tr data-server-name="${eName}">
      <td class="sl-check">
        <input type="checkbox" class="server-checkbox" value="${eName}" aria-label="Select ${eName}" />
      </td>
      <td class="sl-name">${eName}</td>
      <td class="sl-host">${eHost}</td>
      <td class="sl-user">${eUser}</td>
      <td class="sl-port">${ePort}</td>
      <td class="sl-actions">
        <button class="btn btn-neutral btn-sm btn-edit-server"
                data-name="${eName}" data-host="${eHost}"
                data-username="${eUser}" data-port="${s.rest_port ?? ""}">Edit</button>
        <button class="btn btn-kill btn-sm btn-delete-server"
                data-name="${eName}">Remove</button>
      </td>
    </tr>`;
  }).join("");

  area.innerHTML = `
    <div class="bulk-bar" id="bulk-bar" style="display:none;">
      <span id="bulk-count">0 selected</span>
      <div class="bulk-actions">
        <button id="btn-bulk-pw" class="btn btn-neutral btn-sm">Update Password…</button>
        <button id="btn-bulk-delete" class="btn btn-danger btn-sm">Delete Selected</button>
      </div>
    </div>
    <table class="server-list-table">
      <thead>
        <tr>
          <th class="sl-check-hdr"><input type="checkbox" id="chk-select-all" title="Select all" /></th>
          <th>NAME</th>
          <th>HOST</th>
          <th>USERNAME</th>
          <th>PORT</th>
          <th>ACTIONS</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;

  // Wire up select-all
  document.getElementById("chk-select-all").addEventListener("change", e => {
    document.querySelectorAll(".server-checkbox").forEach(cb => { cb.checked = e.target.checked; });
    updateBulkBar();
  });

  // Wire up individual checkboxes
  document.querySelectorAll(".server-checkbox").forEach(cb => {
    cb.addEventListener("change", () => {
      const all  = document.querySelectorAll(".server-checkbox");
      const chkd = document.querySelectorAll(".server-checkbox:checked");
      const selAll = document.getElementById("chk-select-all");
      if (selAll) selAll.indeterminate = chkd.length > 0 && chkd.length < all.length;
      if (selAll) selAll.checked = chkd.length === all.length && all.length > 0;
      updateBulkBar();
    });
  });

  // Wire up row edit/delete buttons
  area.querySelectorAll(".btn-edit-server").forEach(btn => {
    btn.addEventListener("click", () => {
      openEditServerForm(
        btn.dataset.name, btn.dataset.host,
        btn.dataset.username, btn.dataset.port || null
      );
    });
  });
  area.querySelectorAll(".btn-delete-server").forEach(btn => {
    btn.addEventListener("click", () => confirmDeleteServer(btn.dataset.name));
  });

  // Wire up bulk action buttons
  document.getElementById("btn-bulk-delete").addEventListener("click", confirmBulkDelete);
  document.getElementById("btn-bulk-pw").addEventListener("click", openBulkPasswordModal);

  updateBulkBar();
}

/** Return the list of currently checked server names. */
function getSelectedServerNames() {
  return [...document.querySelectorAll(".server-checkbox:checked")].map(cb => cb.value);
}

/** Show/hide and update the bulk action bar based on current selection. */
function updateBulkBar() {
  const bar  = document.getElementById("bulk-bar");
  if (!bar) return;
  const sel  = getSelectedServerNames();
  if (sel.length === 0) {
    bar.style.display = "none";
  } else {
    bar.style.display = "flex";
    document.getElementById("bulk-count").textContent =
      `${sel.length} server${sel.length !== 1 ? "s" : ""} selected`;
  }
}

/** Confirm before bulk-deleting selected servers. */
function confirmBulkDelete() {
  const names = getSelectedServerNames();
  if (names.length === 0) return;
  _serverDeleteTarget = names;  // reuse existing target field; now accepts array too
  document.getElementById("modal-server-delete-msg").textContent =
    `Remove ${names.length} server${names.length !== 1 ? "s" : ""}? (${names.join(", ")})`;
  const errEl = document.getElementById("modal-server-delete-error");
  errEl.textContent = "";
  errEl.style.display = "none";
  openModal("modal-server-delete");
}

/** Open the bulk-password modal. */
function openBulkPasswordModal() {
  const names = getSelectedServerNames();
  if (names.length === 0) return;
  document.getElementById("bulk-pw-target-names").textContent =
    `Updating ${names.length} server${names.length !== 1 ? "s" : ""}: ${names.join(", ")}`;
  document.getElementById("bulk-pw-input").value = "";
  document.getElementById("bulk-pw-confirm").value = "";
  const errEl = document.getElementById("modal-bulk-pw-error");
  errEl.textContent = "";
  errEl.style.display = "none";
  openModal("modal-bulk-password");
}

/** Submit bulk password update. */
async function submitBulkPassword() {
  const names = getSelectedServerNames();
  const pw    = document.getElementById("bulk-pw-input").value;
  const pwc   = document.getElementById("bulk-pw-confirm").value;
  const errEl = document.getElementById("modal-bulk-pw-error");
  errEl.textContent = "";
  errEl.style.display = "none";

  if (!pw) { errEl.textContent = "Password cannot be empty."; errEl.style.display = "block"; return; }
  if (pw !== pwc) { errEl.textContent = "Passwords do not match."; errEl.style.display = "block"; return; }

  const saveBtn = document.getElementById("btn-bulk-pw-save");
  saveBtn.disabled = true;
  saveBtn.textContent = "Updating…";

  try {
    const resp = await fetch(`${API_BASE_URL}/servers/bulk/password`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({ names, password: pw }),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.detail ?? `HTTP ${resp.status}`);
    }
    const data = await resp.json();
    const s = data.data?.summary ?? {};
    showToast(`Password updated for ${s.updated ?? names.length} server(s).`, "ok");
    closeModal("modal-bulk-password");
    openModal("modal-servers");
    await refreshServerList();
  } catch (err) {
    errEl.textContent = `Error: ${err.message}`;
    errEl.style.display = "block";
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "Update Password";
  }
}

/**
 * openAddServerForm — show the add/edit form modal pre-cleared for a new server.
 */
function openAddServerForm() {
  document.getElementById("server-form-heading").textContent = "Add Server";
  document.getElementById("server-form-mode").value = "add";
  document.getElementById("server-form-original-name").value = "";
  document.getElementById("sf-name").value = "";
  document.getElementById("sf-name").disabled = false;
  document.getElementById("sf-host").value = "";
  document.getElementById("sf-username").value = "";
  document.getElementById("sf-password").value = "";
  document.getElementById("sf-port").value = "";
  document.getElementById("sf-password-hint").style.display = "none";

  const errEl = document.getElementById("modal-server-form-error");
  errEl.textContent = "";
  errEl.style.display = "none";

  openModal("modal-server-form");
  document.getElementById("sf-name").focus();
}

/**
 * openEditServerForm — show the form modal pre-filled for editing.
 */
function openEditServerForm(name, host, username, restPort) {
  document.getElementById("server-form-heading").textContent = "Edit Server";
  document.getElementById("server-form-mode").value = "edit";
  document.getElementById("server-form-original-name").value = name;
  document.getElementById("sf-name").value = name;
  document.getElementById("sf-name").disabled = true;  // name is the PK, can't rename
  document.getElementById("sf-host").value = host;
  document.getElementById("sf-username").value = username;
  document.getElementById("sf-password").value = "";
  document.getElementById("sf-port").value = restPort ?? "";
  document.getElementById("sf-password-hint").style.display = "";

  const errEl = document.getElementById("modal-server-form-error");
  errEl.textContent = "";
  errEl.style.display = "none";

  openModal("modal-server-form");
  document.getElementById("sf-host").focus();
}

/**
 * saveServerForm — POST (add) or PUT (edit) based on form mode.
 */
async function saveServerForm() {
  const mode     = document.getElementById("server-form-mode").value;
  const origName = document.getElementById("server-form-original-name").value;
  const name     = document.getElementById("sf-name").value.trim();
  const host     = document.getElementById("sf-host").value.trim();
  const username = document.getElementById("sf-username").value.trim();
  const password = document.getElementById("sf-password").value;
  const portRaw  = document.getElementById("sf-port").value.trim();
  const restPort = portRaw ? parseInt(portRaw, 10) : null;

  const errEl = document.getElementById("modal-server-form-error");
  errEl.textContent = "";
  errEl.style.display = "none";

  if (!name)     { errEl.textContent = "Name is required.";     errEl.style.display = "block"; return; }
  if (!host)     { errEl.textContent = "Host is required.";     errEl.style.display = "block"; return; }
  if (!username) { errEl.textContent = "Username is required."; errEl.style.display = "block"; return; }
  if (mode === "add" && !password) {
    errEl.textContent = "Password is required for a new server.";
    errEl.style.display = "block";
    return;
  }

  const saveBtn = document.getElementById("btn-server-form-save");
  saveBtn.disabled = true;
  saveBtn.textContent = "Saving…";

  try {
    let resp;
    if (mode === "add") {
      resp = await fetch(`${API_BASE_URL}/servers/`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ name, host, username, password, rest_port: restPort }),
      });
    } else {
      const body = { host, username, rest_port: restPort };
      if (password) body.password = password;
      resp = await fetch(`${API_BASE_URL}/servers/${encodeURIComponent(origName)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify(body),
      });
    }

    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.detail ?? data.error ?? `HTTP ${resp.status}`);
    }

    const verb = mode === "add" ? "added" : "updated";
    showToast(`Server "${name}" ${verb} successfully.`, "ok");
    closeModal("modal-server-form");
    await refreshServerList();
    // Re-run poll (IxNetwork Web probe + RestPy) so new server row gets heartbeat/deployment.
    await triggerRefresh();

  } catch (err) {
    errEl.textContent = `Error: ${err.message}`;
    errEl.style.display = "block";
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "Save";
  }
}

/**
 * testServerConnection — POST /servers/{name}/test and show result inline.
 */
async function testServerConnection() {
  const mode     = document.getElementById("server-form-mode").value;
  const origName = document.getElementById("server-form-original-name").value;
  const name     = mode === "add"
    ? document.getElementById("sf-name").value.trim()
    : origName;

  const errEl = document.getElementById("modal-server-form-error");
  errEl.textContent = "";
  errEl.style.display = "none";

  if (mode === "add") {
    errEl.textContent = "Save the server first, then test the connection.";
    errEl.style.display = "block";
    return;
  }

  if (!name) {
    errEl.textContent = "No server name available to test.";
    errEl.style.display = "block";
    return;
  }

  const testBtn = document.getElementById("btn-server-form-test");
  testBtn.disabled = true;
  testBtn.textContent = "Testing…";

  try {
    const resp = await fetch(`${API_BASE_URL}/servers/${encodeURIComponent(name)}/test`, {
      method: "POST",
      headers: { "Accept": "application/json" },
    });
    const data = await resp.json();
    if (data.status === "ok") {
      showToast(data.message, "ok");
    } else {
      errEl.textContent = `Connection failed: ${data.message}`;
      errEl.style.display = "block";
    }
  } catch (err) {
    errEl.textContent = `Test error: ${err.message}`;
    errEl.style.display = "block";
  } finally {
    testBtn.disabled = false;
    testBtn.textContent = "Test Connection";
  }
}

/**
 * confirmDeleteServer — show the delete-confirmation modal.
 */
function confirmDeleteServer(name) {
  _serverDeleteTarget = name;
  document.getElementById("modal-server-delete-msg").textContent =
    `Remove server "${name}"? This will not affect running IxNetwork sessions.`;
  const errEl = document.getElementById("modal-server-delete-error");
  errEl.textContent = "";
  errEl.style.display = "none";
  openModal("modal-server-delete");
}

/**
 * deleteServer — handles both single (string) and bulk (array) targets.
 *   _serverDeleteTarget is either a string (single) or string[] (bulk).
 */
async function deleteServer() {
  if (!_serverDeleteTarget) return;

  const isBulk  = Array.isArray(_serverDeleteTarget);
  const names   = isBulk ? _serverDeleteTarget : [_serverDeleteTarget];

  const deleteBtn = document.getElementById("btn-server-delete-confirm");
  const errEl     = document.getElementById("modal-server-delete-error");
  deleteBtn.disabled = true;
  deleteBtn.textContent = "Removing…";

  try {
    let resp;
    if (isBulk) {
      resp = await fetch(`${API_BASE_URL}/servers/bulk`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ names }),
      });
    } else {
      resp = await fetch(`${API_BASE_URL}/servers/${encodeURIComponent(names[0])}`, {
        method: "DELETE",
        headers: { "Accept": "application/json" },
      });
    }

    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.detail ?? `HTTP ${resp.status}`);
    }

    const label = isBulk ? `${names.length} servers` : `"${names[0]}"`;
    showToast(`${label} removed.`, "ok");
    closeModal("modal-server-delete");
    _serverDeleteTarget = null;
    await refreshServerList();
  } catch (err) {
    errEl.textContent = `Error: ${err.message}`;
    errEl.style.display = "block";
    deleteBtn.disabled = false;
    deleteBtn.textContent = "Remove";
  }
}

// ---------------------------------------------------------------------------
// Bulk Import (CSV)
// ---------------------------------------------------------------------------

/**
 * openBulkImport — show the bulk import modal.
 */
function openBulkImport() {
  document.getElementById("bulk-import-textarea").value = "";
  document.getElementById("bulk-import-preview").innerHTML = "";
  const errEl = document.getElementById("modal-bulk-import-error");
  errEl.textContent = "";
  errEl.style.display = "none";
  openModal("modal-bulk-import");
  document.getElementById("bulk-import-textarea").focus();
}

/**
 * parseBulkImportCSV — parse the CSV text and return validated rows + errors.
 *
 * Accepted formats (with or without header row):
 *   name,host,username,password[,rest_port]
 *   name,host,username,password,443
 *
 * Returns { rows: ServerCreateRequest[], errors: string[] }
 */
function parseBulkImportCSV(text) {
  const lines  = text.trim().split(/\r?\n/).filter(l => l.trim() && !l.trim().startsWith("#"));
  const rows   = [];
  const errors = [];

  // Detect and skip header row
  const first = lines[0]?.toLowerCase() ?? "";
  const startIdx = (first.includes("name") && first.includes("host")) ? 1 : 0;

  lines.slice(startIdx).forEach((line, i) => {
    const lineNum = startIdx + i + 1;
    // Basic CSV split (handles quoted fields with commas)
    const cols = line.match(/(".*?"|[^,]+|(?<=,)(?=,)|(?<=,)$|^(?=,))/g)
      ?.map(c => c.replace(/^"|"$/g, "").trim()) ?? line.split(",").map(c => c.trim());

    const [name, host, username, password, restPortRaw] = cols;
    const restPort = restPortRaw ? parseInt(restPortRaw, 10) : null;

    if (!name)     { errors.push(`Line ${lineNum}: missing name`);     return; }
    if (!host)     { errors.push(`Line ${lineNum}: missing host`);     return; }
    if (!username) { errors.push(`Line ${lineNum}: missing username`); return; }
    if (!password) { errors.push(`Line ${lineNum}: missing password`); return; }
    if (restPortRaw && isNaN(restPort)) {
      errors.push(`Line ${lineNum}: invalid rest_port "${restPortRaw}"`);
      return;
    }

    rows.push({ name, host, username, password, rest_port: restPort });
  });

  return { rows, errors };
}

/**
 * previewBulkImport — parse textarea contents and show a live preview table.
 */
function previewBulkImport() {
  const text    = document.getElementById("bulk-import-textarea").value;
  const preview = document.getElementById("bulk-import-preview");
  const errEl   = document.getElementById("modal-bulk-import-error");
  errEl.textContent = "";
  errEl.style.display = "none";

  if (!text.trim()) { preview.innerHTML = ""; return; }

  const { rows, errors } = parseBulkImportCSV(text);

  if (errors.length) {
    errEl.textContent = errors.join(" · ");
    errEl.style.display = "block";
  }

  if (rows.length === 0) { preview.innerHTML = ""; return; }

  const tRows = rows.map(r => `
    <tr>
      <td>${escapeHtml(r.name)}</td>
      <td>${escapeHtml(r.host)}</td>
      <td>${escapeHtml(r.username)}</td>
      <td>••••••</td>
      <td>${r.rest_port ?? "auto"}</td>
    </tr>`).join("");

  preview.innerHTML = `
    <p class="import-preview-label">${rows.length} server${rows.length !== 1 ? "s" : ""} to import:</p>
    <table class="server-list-table import-preview-table">
      <thead><tr><th>NAME</th><th>HOST</th><th>USERNAME</th><th>PASSWORD</th><th>PORT</th></tr></thead>
      <tbody>${tRows}</tbody>
    </table>`;
}

/**
 * submitBulkImport — POST /servers/bulk with the parsed rows.
 */
async function submitBulkImport() {
  const text  = document.getElementById("bulk-import-textarea").value;
  const errEl = document.getElementById("modal-bulk-import-error");
  errEl.textContent = "";
  errEl.style.display = "none";

  const { rows, errors } = parseBulkImportCSV(text);

  if (errors.length) {
    errEl.textContent = "Fix errors before importing: " + errors.join(" · ");
    errEl.style.display = "block";
    return;
  }
  if (rows.length === 0) {
    errEl.textContent = "Nothing to import — paste at least one server row.";
    errEl.style.display = "block";
    return;
  }

  const importBtn = document.getElementById("btn-bulk-import-submit");
  importBtn.disabled = true;
  importBtn.textContent = "Importing…";

  try {
    const resp = await fetch(`${API_BASE_URL}/servers/bulk`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({ servers: rows }),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.detail ?? `HTTP ${resp.status}`);
    }
    const data = await resp.json();
    const s = data.data?.summary ?? {};
    const parts = [];
    if (s.created) parts.push(`${s.created} added`);
    if (s.updated) parts.push(`${s.updated} updated`);
    if (s.errors)  parts.push(`${s.errors} failed`);
    showToast(`Import complete: ${parts.join(", ")}.`, s.errors ? "error" : "ok");

    if (s.errors) {
      const failedNames = data.data.results
        .filter(r => r.action === "error")
        .map(r => `${r.name}: ${r.message}`)
        .join("; ");
      errEl.textContent = `Some entries failed: ${failedNames}`;
      errEl.style.display = "block";
    } else {
      closeModal("modal-bulk-import");
      openModal("modal-servers");
      await refreshServerList();
      await triggerRefresh();
    }
  } catch (err) {
    errEl.textContent = `Error: ${err.message}`;
    errEl.style.display = "block";
  } finally {
    importBtn.disabled = false;
    importBtn.textContent = "Import";
  }
}

// ----- Server modal event listeners ------------------------------------

document.getElementById("btn-manage-servers").addEventListener("click", openServerManager);

document.getElementById("btn-add-server").addEventListener("click", openAddServerForm);

document.getElementById("btn-bulk-import").addEventListener("click", openBulkImport);

document.getElementById("btn-server-form-back").addEventListener("click", () => {
  closeModal("modal-server-form");
  openModal("modal-servers");
});

document.getElementById("btn-server-form-save").addEventListener("click", saveServerForm);

document.getElementById("btn-server-form-test").addEventListener("click", testServerConnection);

document.getElementById("btn-server-delete-cancel").addEventListener("click", () => {
  closeModal("modal-server-delete");
  openModal("modal-servers");
});

document.getElementById("btn-server-delete-confirm").addEventListener("click", deleteServer);

document.getElementById("btn-toggle-password").addEventListener("click", () => {
  const pwField = document.getElementById("sf-password");
  const isHidden = pwField.type === "password";
  pwField.type = isHidden ? "text" : "password";
});

// Bulk password modal
document.getElementById("btn-bulk-pw-save").addEventListener("click", submitBulkPassword);
document.getElementById("btn-bulk-pw-cancel").addEventListener("click", () => {
  closeModal("modal-bulk-password");
  openModal("modal-servers");
});

// Bulk import modal
document.getElementById("btn-bulk-import-back").addEventListener("click", () => {
  closeModal("modal-bulk-import");
  openModal("modal-servers");
});
document.getElementById("btn-bulk-import-submit").addEventListener("click", submitBulkImport);
document.getElementById("bulk-import-textarea").addEventListener("input", previewBulkImport);

// ---------------------------------------------------------------------------
// Poller Settings
// ---------------------------------------------------------------------------

/**
 * fetchPollConfig — GET /poll/config, update the control-bar display.
 */
async function fetchPollConfig() {
  try {
    const resp = await fetch(`${API_BASE_URL}/poll/config`, {
      headers: { "Accept": "application/json" },
    });
    if (!resp.ok) return;
    const body = await resp.json();
    const secs = body.data?.interval_seconds ?? 60;
    _updatePollIntervalDisplay(secs);
  } catch (_) {
    // Non-fatal — display keeps its default
  }
}

function _updatePollIntervalDisplay(seconds) {
  const el = document.getElementById("poll-interval-display");
  if (el) el.textContent = `${seconds}s`;
}

/**
 * openPollerSettings — load current config and show the modal.
 */
async function openPollerSettings() {
  const errEl = document.getElementById("modal-poller-error");
  errEl.textContent = "";
  errEl.style.display = "none";

  // Pre-fill with current value shown in the button
  const currentText = document.getElementById("poll-interval-display")?.textContent ?? "60s";
  const currentVal  = parseInt(currentText, 10) || 60;
  document.getElementById("poller-interval-input").value = currentVal;

  openModal("modal-poller-settings");
  document.getElementById("poller-interval-input").focus();
}

/**
 * savePollerConfig — PATCH /poll/config with the new interval.
 */
async function savePollerConfig() {
  const raw    = document.getElementById("poller-interval-input").value.trim();
  const secs   = parseInt(raw, 10);
  const errEl  = document.getElementById("modal-poller-error");
  errEl.textContent = "";
  errEl.style.display = "none";

  if (!raw || isNaN(secs) || secs < 10 || secs > 3600) {
    errEl.textContent = "Interval must be a number between 10 and 3600.";
    errEl.style.display = "block";
    return;
  }

  const saveBtn = document.getElementById("btn-poller-save");
  saveBtn.disabled = true;
  saveBtn.textContent = "Saving…";

  try {
    const resp = await fetch(`${API_BASE_URL}/poll/config`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({ interval_seconds: secs }),
    });

    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.detail ?? `HTTP ${resp.status}`);
    }

    _updatePollIntervalDisplay(secs);
    showToast(`Poll interval set to ${secs}s.`, "ok");
    closeModal("modal-poller-settings");

  } catch (err) {
    errEl.textContent = `Error: ${err.message}`;
    errEl.style.display = "block";
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "Save";
  }
}

document.getElementById("btn-poller-settings").addEventListener("click", openPollerSettings);
document.getElementById("btn-poller-save").addEventListener("click", savePollerConfig);
document.getElementById("poller-interval-input").addEventListener("keydown", e => {
  if (e.key === "Enter") savePollerConfig();
});

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------
fetchSessions();
fetchPollConfig();
