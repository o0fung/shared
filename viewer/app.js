"use strict";

const DATA_URL = "data/synchronized_walk.csv";
const DEFAULT_CHANNEL_SUFFIXES = ["master_right_walk_acc_y", "slave_left_walk_acc_y"];
const COLORS = [
  "#5eead4",
  "#60a5fa",
  "#fbbf24",
  "#f472b6",
  "#a78bfa",
  "#fb7185",
  "#34d399",
  "#f97316",
];
const MARKER_CONFIG = {
  blue: { color: "#60a5fa", label: "Blue" },
  red: { color: "#ef4444", label: "Red" },
};
const VIEWER_PREFS_STORAGE_KEY = "gait-viewer-prefs";
const VIEWER_PREFS_SCHEMA_VERSION = 1;

const elements = {
  status: document.querySelector("#status"),
  rangeStart: document.querySelector("#range-start"),
  rangeEnd: document.querySelector("#range-end"),
  applyRange: document.querySelector("#apply-range"),
  resetRange: document.querySelector("#reset-range"),
  channelSearch: document.querySelector("#channel-search"),
  channelList: document.querySelector("#channel-list"),
  selectedCount: document.querySelector("#selected-count"),
  selectAll: document.querySelector("#select-all"),
  clearAll: document.querySelector("#clear-all"),
  emptyState: document.querySelector("#empty-state"),
  plot: document.querySelector("#plot"),
};

const state = {
  rows: [],
  channels: [],
  selectedChannels: new Set(),
  fullRange: [0, 0],
  markers: {
    blue: null,
    red: null,
  },
};

function defaultSelectedChannels() {
  return new Set(
    DEFAULT_CHANNEL_SUFFIXES.filter((channel) => state.channels.includes(channel)),
  );
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function findNearestRow(rows, targetFid) {
  if (rows.length === 0 || !Number.isFinite(targetFid)) {
    return null;
  }

  let nearest = rows[0];
  let nearestDistance = Math.abs(rows[0].fid - targetFid);
  for (let index = 1; index < rows.length; index += 1) {
    const candidate = rows[index];
    const distance = Math.abs(candidate.fid - targetFid);
    if (distance < nearestDistance) {
      nearest = candidate;
      nearestDistance = distance;
    }
  }
  return nearest;
}

function normalizeMarkerFid(rawFid, visibleRows, range) {
  if (!Number.isFinite(rawFid) || visibleRows.length === 0) {
    return null;
  }
  const clampedFid = clamp(rawFid, range[0], range[1]);
  return findNearestRow(visibleRows, clampedFid)?.fid ?? null;
}

function formatMagnitude(value) {
  return Number.isFinite(value) ? value.toFixed(4) : "n/a";
}

function formatMarkerTime(fid) {
  return `${(fid / 50).toFixed(2)}s`;
}

function buildMarkerOverlay(selectedChannels, subplotMeta, visibleRows) {
  // Marker rendering flow:
  // 1) Resolve blue/red marker FIDs to concrete visible rows.
  // 2) Draw full-height shared-x lines.
  // 3) For each subplot, print right-edge magnitude labels with FID/time context.
  // This keeps marker visuals synchronized with zoomed ranges and channel sets.
  const markerRows = Object.entries(state.markers)
    .map(([key, markerFid]) => {
      if (!Number.isFinite(markerFid)) {
        return null;
      }
      const row = findNearestRow(visibleRows, markerFid);
      if (!row) {
        return null;
      }
      return { key, markerFid: row.fid, row };
    })
    .filter(Boolean);

  if (markerRows.length === 0) {
    return { shapes: [], annotations: [] };
  }

  const shapes = markerRows.map((marker) => ({
    type: "line",
    xref: "x",
    yref: "paper",
    x0: marker.markerFid,
    x1: marker.markerFid,
    y0: 0,
    y1: 1,
    line: {
      color: MARKER_CONFIG[marker.key].color,
      width: 1.5,
      dash: "dot",
    },
  }));

  const rightEdgeAnnotations = [];
  const markerOrder = ["blue", "red"];
  const markerSlotOffset = {
    blue: 0,
    red: 1,
  };
  subplotMeta.forEach((subplot, index) => {
    const channel = selectedChannels[index];
    if (!channel) {
      return;
    }

    markerOrder.forEach((markerKey) => {
      const marker = markerRows.find((entry) => entry.key === markerKey);
      if (!marker) {
        return;
      }
      const magnitude = marker.row[channel];
      if (!Number.isFinite(magnitude)) {
        return;
      }
      rightEdgeAnnotations.push({
        xref: "paper",
        yref: "paper",
        x: 0.995,
        y: subplot.domainTop - markerSlotOffset[marker.key] * 0.038,
        xanchor: "right",
        yanchor: "top",
        showarrow: false,
        yshift: -2,
        text: `${MARKER_CONFIG[marker.key].label}: ${formatMagnitude(magnitude)} @ FID ${marker.markerFid} (${formatMarkerTime(marker.markerFid)})`,
        font: {
          size: 10,
          color: MARKER_CONFIG[marker.key].color,
        },
        bgcolor: "rgba(10,15,29,0.92)",
        bordercolor: MARKER_CONFIG[marker.key].color,
        borderwidth: 1,
        borderpad: 2,
      });
    });
  });

  return { shapes, annotations: rightEdgeAnnotations };
}

function fidFromContextMenu(event) {
  const fullLayout = elements.plot._fullLayout;
  const xAxis = fullLayout?.xaxis;
  const size = fullLayout?._size;
  if (!xAxis || !Array.isArray(xAxis.range) || !size) {
    return null;
  }

  // Right-click does not emit Plotly point data, so we translate pointer
  // pixels into shared x-axis coordinates and reject clicks outside the main
  // plotting rectangle to avoid hijacking context menu in side margins.
  const rect = elements.plot.getBoundingClientRect();
  const relativeX = event.clientX - rect.left - size.l;
  const relativeY = event.clientY - rect.top - size.t;
  if (
    !Number.isFinite(relativeX) ||
    !Number.isFinite(relativeY) ||
    relativeX < 0 ||
    relativeX > size.w ||
    relativeY < 0 ||
    relativeY > size.h
  ) {
    return null;
  }

  const axisStart = Number(xAxis.range[0]);
  const axisEnd = Number(xAxis.range[1]);
  if (!Number.isFinite(axisStart) || !Number.isFinite(axisEnd) || size.w <= 0) {
    return null;
  }

  const fraction = relativeX / size.w;
  return axisStart + (axisEnd - axisStart) * fraction;
}

function parseCsv(text) {
  const lines = text.trimEnd().split(/\r?\n/);
  if (lines.length < 2) {
    throw new Error("The synchronized CSV contains no data rows.");
  }

  // This viewer consumes the numeric CSV generated by sync_walk_csv.py. Its
  // fields contain no commas or quoted text, so direct splitting avoids shipping
  // a second parsing dependency with the public page.
  const headers = lines[0].split(",");
  const rows = lines.slice(1).map((line) => {
    const values = line.split(",");
    return Object.fromEntries(
      headers.map((header, index) => {
        const rawValue = values[index] ?? "";
        return [header, rawValue === "" ? null : Number(rawValue)];
      }),
    );
  });

  if (headers[0] !== "fid" || rows.some((row) => !Number.isFinite(row.fid))) {
    throw new Error("The synchronized CSV has an invalid fid column.");
  }
  return { headers, rows };
}

function channelLabel(channel) {
  return channel
    .replace("master_right_", "Right · ")
    .replace("slave_left_", "Left · ")
    .replaceAll("_", " ");
}

function filteredChannels() {
  const query = elements.channelSearch.value.trim().toLowerCase();
  return state.channels.filter(
    (channel) =>
      channel.toLowerCase().includes(query) ||
      channelLabel(channel).toLowerCase().includes(query),
  );
}

function updateSelectedCount() {
  elements.selectedCount.textContent = `${state.selectedChannels.size} selected`;
}

function renderChannelList() {
  elements.channelList.replaceChildren();
  for (const channel of filteredChannels()) {
    const label = document.createElement("label");
    label.className = "channel-option";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selectedChannels.has(channel);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        state.selectedChannels.add(channel);
      } else {
        state.selectedChannels.delete(channel);
      }
      updateSelectedCount();
      saveViewerPreferences();
      renderPlot();
    });

    const text = document.createElement("span");
    text.textContent = channelLabel(channel);
    label.append(checkbox, text);
    elements.channelList.append(label);
  }
  updateSelectedCount();
}

function selectedRange() {
  const requestedStart = Number(elements.rangeStart.value);
  const requestedEnd = Number(elements.rangeEnd.value);
  const [fullStart, fullEnd] = state.fullRange;
  if (!Number.isFinite(requestedStart) || !Number.isFinite(requestedEnd)) {
    throw new Error("Both FID range values must be numbers.");
  }
  if (requestedStart >= requestedEnd) {
    throw new Error("The start FID must be smaller than the end FID.");
  }
  return [
    Math.max(fullStart, Math.round(requestedStart)),
    Math.min(fullEnd, Math.round(requestedEnd)),
  ];
}

function saveViewerPreferences() {
  try {
    const [fullStart, fullEnd] = state.fullRange;
    if (!Number.isFinite(fullStart) || !Number.isFinite(fullEnd)) {
      return;
    }

    let rangeStart = Number(elements.rangeStart.value);
    let rangeEnd = Number(elements.rangeEnd.value);
    if (!Number.isFinite(rangeStart) || !Number.isFinite(rangeEnd)) {
      rangeStart = fullStart;
      rangeEnd = fullEnd;
    }
    rangeStart = clamp(Math.round(rangeStart), fullStart, fullEnd);
    rangeEnd = clamp(Math.round(rangeEnd), fullStart, fullEnd);
    if (rangeStart >= rangeEnd) {
      rangeStart = fullStart;
      rangeEnd = fullEnd;
    }

    const selectedChannels = [...state.selectedChannels].filter((channel) =>
      state.channels.includes(channel),
    );
    const payload = {
      version: VIEWER_PREFS_SCHEMA_VERSION,
      rangeStart,
      rangeEnd,
      selectedChannels,
    };
    localStorage.setItem(VIEWER_PREFS_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // Persistence is best-effort: rendering and interaction should continue.
  }
}

function loadViewerPreferences() {
  try {
    const raw = localStorage.getItem(VIEWER_PREFS_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw);
    if (parsed?.version !== VIEWER_PREFS_SCHEMA_VERSION) {
      return null;
    }

    // Restore flow:
    // 1) sanitize channel ids against current CSV headers
    // 2) sanitize range against dataset bounds
    // 3) if restored values cannot produce a usable state, fall back to defaults
    const available = new Set(state.channels);
    let selectedChannels = Array.isArray(parsed.selectedChannels)
      ? parsed.selectedChannels.filter((channel) => available.has(channel))
      : [];
    if (selectedChannels.length === 0) {
      selectedChannels = [...defaultSelectedChannels()];
    }

    const [fullStart, fullEnd] = state.fullRange;
    let rangeStart = Number(parsed.rangeStart);
    let rangeEnd = Number(parsed.rangeEnd);
    if (!Number.isFinite(rangeStart) || !Number.isFinite(rangeEnd)) {
      rangeStart = fullStart;
      rangeEnd = fullEnd;
    }
    rangeStart = clamp(Math.round(rangeStart), fullStart, fullEnd);
    rangeEnd = clamp(Math.round(rangeEnd), fullStart, fullEnd);
    if (rangeStart >= rangeEnd) {
      rangeStart = fullStart;
      rangeEnd = fullEnd;
    }

    return { selectedChannels, rangeStart, rangeEnd };
  } catch {
    return null;
  }
}

function showRangeError(message) {
  elements.status.textContent = message;
  elements.status.classList.add("error");
}

function renderPlot() {
  const selected = state.channels.filter((channel) =>
    state.selectedChannels.has(channel),
  );
  elements.emptyState.hidden = selected.length > 0;
  elements.plot.hidden = selected.length === 0;
  if (selected.length === 0) {
    Plotly.purge(elements.plot);
    return;
  }

  let range;
  try {
    range = selectedRange();
  } catch (error) {
    showRangeError(error.message);
    return;
  }

  elements.status.classList.remove("error");
  elements.status.textContent = `${state.rows.length.toLocaleString()} samples · ${selected.length} subplot${selected.length === 1 ? "" : "s"}`;
  const visibleRows = state.rows.filter(
    (row) => row.fid >= range[0] && row.fid <= range[1],
  );

  // Give every trace its own y-axis domain while matching all x-axes to the
  // first one. The final subplot alone renders x tick labels, producing stacked
  // independent scales with synchronized zoom, pan, and hover positioning.
  const layout = {
    paper_bgcolor: "#111827",
    plot_bgcolor: "#111827",
    font: { color: "#c9d5e5", size: 11 },
    height: Math.max(560, selected.length * 190),
    margin: { l: 130, r: 30, t: 28, b: 55 },
    hovermode: "x unified",
    showlegend: false,
    uirevision: `${range[0]}:${range[1]}:${selected.join("|")}`,
  };
  const subplotMeta = [];
  const traces = selected.map((channel, index) => {
    const axisNumber = index + 1;
    const axisSuffix = axisNumber === 1 ? "" : String(axisNumber);
    const cellHeight = 1 / selected.length;
    const domainTop = 1 - index * cellHeight;
    const domainBottom = 1 - (index + 1) * cellHeight + 0.035;
    const xAxisName = `xaxis${axisSuffix}`;
    const yAxisName = `yaxis${axisSuffix}`;

    layout[xAxisName] = {
      anchor: `y${axisSuffix}`,
      matches: axisNumber === 1 ? undefined : "x",
      range,
      showticklabels: index === selected.length - 1,
      title: index === selected.length - 1 ? { text: "FID" } : undefined,
      gridcolor: "#263348",
      zerolinecolor: "#3b4d68",
    };
    layout[yAxisName] = {
      anchor: `x${axisSuffix}`,
      domain: [Math.max(0, domainBottom), domainTop],
      title: { text: channelLabel(channel), standoff: 12 },
      gridcolor: "#263348",
      zerolinecolor: "#3b4d68",
      automargin: true,
    };
    subplotMeta.push({
      yAxisRef: `y${axisSuffix}`,
      domainTop,
    });

    return {
      type: "scattergl",
      mode: "lines",
      name: channelLabel(channel),
      x: visibleRows.map((row) => row.fid),
      y: visibleRows.map((row) => row[channel]),
      xaxis: `x${axisSuffix}`,
      yaxis: `y${axisSuffix}`,
      connectgaps: false,
      line: { color: COLORS[index % COLORS.length], width: 1.35 },
      hovertemplate: "%{y:.4f}<extra></extra>",
    };
  });
  const markerOverlay = buildMarkerOverlay(selected, subplotMeta, visibleRows);
  layout.shapes = markerOverlay.shapes;
  layout.annotations = markerOverlay.annotations;

  Plotly.react(elements.plot, traces, layout, {
    responsive: true,
    displaylogo: false,
    scrollZoom: true,
    modeBarButtonsToRemove: ["lasso2d", "select2d"],
  });

  elements.plot.removeAllListeners?.("plotly_relayout");
  elements.plot.removeAllListeners?.("plotly_click");
  elements.plot.on("plotly_relayout", (event) => {
    const start = event["xaxis.range[0]"];
    const end = event["xaxis.range[1]"];
    if (Number.isFinite(start) && Number.isFinite(end)) {
      elements.rangeStart.value = Math.round(start);
      elements.rangeEnd.value = Math.round(end);
      saveViewerPreferences();
    }
  });
  elements.plot.on("plotly_click", (event) => {
    const clickedFid = event?.points?.[0]?.x;
    const markerFid = normalizeMarkerFid(clickedFid, visibleRows, range);
    if (!Number.isFinite(markerFid)) {
      return;
    }
    state.markers.blue = markerFid;
    renderPlot();
  });
  elements.plot.oncontextmenu = (event) => {
    const clickedFid = fidFromContextMenu(event);
    const markerFid = normalizeMarkerFid(clickedFid, visibleRows, range);
    if (!Number.isFinite(markerFid)) {
      return;
    }
    event.preventDefault();
    state.markers.red = markerFid;
    renderPlot();
  };
}

function enableControls() {
  for (const control of [
    elements.rangeStart,
    elements.rangeEnd,
    elements.applyRange,
    elements.resetRange,
    elements.channelSearch,
    elements.selectAll,
    elements.clearAll,
  ]) {
    control.disabled = false;
  }
}

async function loadData() {
  try {
    const response = await fetch(DATA_URL);
    if (!response.ok) {
      throw new Error(`Data request failed with HTTP ${response.status}.`);
    }
    const { headers, rows } = parseCsv(await response.text());
    state.rows = rows;
    state.channels = headers.slice(1);
    state.fullRange = [rows[0].fid, rows.at(-1).fid];
    const restoredPreferences = loadViewerPreferences();
    state.selectedChannels = restoredPreferences
      ? new Set(restoredPreferences.selectedChannels)
      : defaultSelectedChannels();

    elements.rangeStart.min = state.fullRange[0];
    elements.rangeStart.max = state.fullRange[1];
    elements.rangeStart.value = restoredPreferences
      ? restoredPreferences.rangeStart
      : state.fullRange[0];
    elements.rangeEnd.min = state.fullRange[0];
    elements.rangeEnd.max = state.fullRange[1];
    elements.rangeEnd.value = restoredPreferences
      ? restoredPreferences.rangeEnd
      : state.fullRange[1];
    enableControls();
    renderChannelList();
    renderPlot();
  } catch (error) {
    elements.status.textContent = `Unable to load viewer: ${error.message}`;
    elements.status.classList.add("error");
  }
}

elements.applyRange.addEventListener("click", () => {
  renderPlot();
  saveViewerPreferences();
});
elements.resetRange.addEventListener("click", () => {
  [elements.rangeStart.value, elements.rangeEnd.value] = state.fullRange;
  renderPlot();
  saveViewerPreferences();
});
elements.channelSearch.addEventListener("input", renderChannelList);
elements.selectAll.addEventListener("click", () => {
  for (const channel of filteredChannels()) {
    state.selectedChannels.add(channel);
  }
  renderChannelList();
  renderPlot();
  saveViewerPreferences();
});
elements.clearAll.addEventListener("click", () => {
  state.selectedChannels.clear();
  renderChannelList();
  renderPlot();
  saveViewerPreferences();
});

loadData();
