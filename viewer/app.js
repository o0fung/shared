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
const CHANNEL_SIDE_PREFIXES = {
  right: "master_right_",
  left: "slave_left_",
};
const VIEWER_PREFS_STORAGE_KEY = "gait-viewer-prefs";
const VIEWER_PREFS_SCHEMA_VERSION = 2;
const MIN_FID_SPAN = 2;
const COMPACT_SUBPLOT_HEIGHT = 110;
const MOBILE_LAYOUT_MAX_WIDTH = 820;
const MOBILE_PLOT_MIN_HEIGHT = 560;

const elements = {
  status: document.querySelector("#status"),
  rangeStart: document.querySelector("#range-start"),
  rangeEnd: document.querySelector("#range-end"),
  rangeEndSlider: document.querySelector("#range-end-slider"),
  rangeEndSliderValue: document.querySelector("#range-end-slider-value"),
  applyRange: document.querySelector("#apply-range"),
  resetRange: document.querySelector("#reset-range"),
  restoreRange: document.querySelector("#restore-range"),
  invertRight: document.querySelector("#invert-right"),
  invertLeft: document.querySelector("#invert-left"),
  channelSearch: document.querySelector("#channel-search"),
  channelList: document.querySelector("#channel-list"),
  selectedCount: document.querySelector("#selected-count"),
  selectAll: document.querySelector("#select-all"),
  clearAll: document.querySelector("#clear-all"),
  applyChannels: document.querySelector("#apply-channels"),
  restoreChannels: document.querySelector("#restore-channels"),
  emptyState: document.querySelector("#empty-state"),
  plotPanel: document.querySelector(".plot-panel"),
  plot: document.querySelector("#plot"),
};

const state = {
  rows: [],
  channels: [],
  selectedChannels: new Set(),
  fullRange: [0, 0],
  persistedRange: null,
  persistedChannels: new Set(),
  invertedSides: {
    right: false,
    left: false,
  },
  markers: {
    blue: null,
    red: null,
  },
  interaction: {
    horizontalWheelInstalled: false,
  },
  plotHeight: null,
  plotResizeFrame: null,
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

function normalizeMarkerFid(rawFid, dataRows, range) {
  if (!Number.isFinite(rawFid) || dataRows.length === 0) {
    return null;
  }
  const clampedFid = clamp(rawFid, range[0], range[1]);
  return findNearestRow(dataRows, clampedFid)?.fid ?? null;
}

function formatMagnitude(value) {
  return Number.isFinite(value) ? value.toFixed(4) : "n/a";
}

function formatMarkerTime(fid) {
  return `${(fid / 50).toFixed(2)}s`;
}

function displayedChannelValue(row, channel) {
  const value = row[channel];
  if (!Number.isFinite(value)) {
    return value;
  }
  const side = Object.entries(CHANNEL_SIDE_PREFIXES).find(([, prefix]) =>
    channel.startsWith(prefix),
  )?.[0];
  return side && state.invertedSides[side] ? -value : value;
}

function buildMarkerOverlay(selectedChannels, subplotMeta, dataRows) {
  // In-plot annotation flow:
  // 1) Resolve blue/red marker FIDs to concrete visible rows.
  // 2) Draw full-height shared-x lines for active markers.
  // 3) For every subplot, stack its y label, then blue and red values at the
  //    top-right inside its domain. Scale spacing to keep all labels within
  //    compact subplots. The y label is independent of marker state.
  const markerRows = Object.entries(state.markers)
    .map(([key, markerFid]) => {
      if (!Number.isFinite(markerFid)) {
        return null;
      }
      const row = findNearestRow(dataRows, markerFid);
      if (!row) {
        return null;
      }
      return { key, markerFid: row.fid, row };
    })
    .filter(Boolean);

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

  const plotAnnotations = [];
  const markerOrder = ["blue", "red"];
  const markerSlotOffset = {
    blue: 1,
    red: 2,
  };
  subplotMeta.forEach((subplot, index) => {
    const channel = selectedChannels[index];
    if (!channel) {
      return;
    }
    const annotationStep = Math.min(0.038, subplot.domainHeight / 3.2);

    plotAnnotations.push({
      xref: "paper",
      yref: "paper",
      x: 0.995,
      y: subplot.domainTop,
      xanchor: "right",
      yanchor: "top",
      align: "right",
      showarrow: false,
      yshift: -2,
      text: channelLabel(channel),
      font: {
        size: 11,
        color: "#c9d5e5",
      },
      bgcolor: "rgba(10,15,29,0.58)",
      bordercolor: "rgba(201,213,229,0.72)",
      borderwidth: 1,
      borderpad: 2,
    });

    markerOrder.forEach((markerKey) => {
      const marker = markerRows.find((entry) => entry.key === markerKey);
      if (!marker) {
        return;
      }
      const magnitude = displayedChannelValue(marker.row, channel);
      if (!Number.isFinite(magnitude)) {
        return;
      }
      plotAnnotations.push({
        xref: "paper",
        yref: "paper",
        x: 0.995,
        y: subplot.domainTop - markerSlotOffset[marker.key] * annotationStep,
        xanchor: "right",
        yanchor: "top",
        align: "right",
        showarrow: false,
        yshift: -2,
        text: `${MARKER_CONFIG[marker.key].label}: ${formatMagnitude(magnitude)} @ FID ${marker.markerFid} (${formatMarkerTime(marker.markerFid)})`,
        font: {
          size: 10,
          color: MARKER_CONFIG[marker.key].color,
        },
        bgcolor: "rgba(10,15,29,0.58)",
        bordercolor: MARKER_CONFIG[marker.key].color,
        borderwidth: 1,
        borderpad: 2,
      });
    });
  });

  return { shapes, annotations: plotAnnotations };
}

function fidFromContextMenu(event) {
  const pointer = plotPointerFromEvent(event);
  if (!pointer) {
    return null;
  }
  return pointer.fid;
}

function plotPointerFromEvent(event) {
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
  return {
    fid: axisStart + (axisEnd - axisStart) * fraction,
    relativeX,
  };
}

function activeRangeOrFullRange() {
  try {
    return selectedRange();
  } catch {
    return [...state.fullRange];
  }
}

function rangeEndFromDrag(startRange, deltaX, plotWidth) {
  const [fullStart, fullEnd] = state.fullRange;
  const [rangeStart, rangeEnd] = startRange;
  if (!Number.isFinite(plotWidth) || plotWidth <= 0) {
    return startRange;
  }

  const fidPerPixel = (rangeEnd - rangeStart) / plotWidth;
  const nextEnd = clamp(
    rangeEnd - deltaX * fidPerPixel,
    Math.max(fullStart, rangeStart) + MIN_FID_SPAN,
    fullEnd,
  );
  return [rangeStart, Math.round(nextEnd)];
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

function pairedChannelKey(channel) {
  return channel
    .replace(/^(?:master_right|slave_left)_/, "walk_")
    .replace(/^knr_(?:right|left)_/, "knr_");
}

function colorsForSelectedChannels(channels) {
  // Allocation flow:
  // 1) Visit channels in the order they were selected.
  // 2) Give each previously unseen left/right measurement pair the next color.
  // 3) Reuse that color for its counterpart.
  // Colors repeat only after every palette color has been assigned, avoiding
  // collisions between earlier, distinct measurements.
  const colorsByPairKey = new Map();
  const colorsByChannel = new Map();
  for (const channel of channels) {
    const key = pairedChannelKey(channel);
    if (!colorsByPairKey.has(key)) {
      colorsByPairKey.set(key, COLORS[colorsByPairKey.size % COLORS.length]);
    }
    colorsByChannel.set(channel, colorsByPairKey.get(key));
  }
  return colorsByChannel;
}

function pairedYAxisRanges(channels, dataRows) {
  // Range flow:
  // 1) Group only selected left/right counterparts by measurement key.
  // 2) Find the visible-value minimum and maximum across each complete pair.
  // 3) Apply the same padded, explicit range to both pair subplots.
  // This avoids Plotly retaining a broad interaction-derived autorange while
  // retaining independent autoranging for channels without a counterpart.
  const channelsByPairKey = new Map();
  for (const channel of channels) {
    const key = pairedChannelKey(channel);
    const pairedChannels = channelsByPairKey.get(key) ?? [];
    pairedChannels.push(channel);
    channelsByPairKey.set(key, pairedChannels);
  }

  const rangesByChannel = new Map();
  for (const pairedChannels of channelsByPairKey.values()) {
    if (pairedChannels.length < 2) {
      continue;
    }

    let minimum = Infinity;
    let maximum = -Infinity;
    for (const channel of pairedChannels) {
      for (const row of dataRows) {
        const value = displayedChannelValue(row, channel);
        if (Number.isFinite(value)) {
          minimum = Math.min(minimum, value);
          maximum = Math.max(maximum, value);
        }
      }
    }
    if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) {
      continue;
    }

    const span = maximum - minimum;
    const padding = span > 0 ? span * 0.05 : Math.max(Math.abs(minimum) * 0.05, 0.5);
    const range = [minimum - padding, maximum + padding];
    for (const channel of pairedChannels) {
      rangesByChannel.set(channel, range);
    }
  }
  return rangesByChannel;
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

function syncEndRangeSlider() {
  const [fullStart, fullEnd] = state.fullRange;
  const requestedStart = Number(elements.rangeStart.value);
  const requestedEnd = Number(elements.rangeEnd.value);
  if (
    !Number.isFinite(fullStart) ||
    !Number.isFinite(fullEnd) ||
    !Number.isFinite(requestedStart) ||
    !Number.isFinite(requestedEnd)
  ) {
    return;
  }

  const min = clamp(Math.round(requestedStart) + 1, fullStart, fullEnd);
  const value = clamp(Math.round(requestedEnd), min, fullEnd);
  elements.rangeEndSlider.min = min;
  elements.rangeEndSlider.max = fullEnd;
  elements.rangeEndSlider.value = value;
  elements.rangeEndSliderValue.value = value;
}

function rangeFromRelayout(event) {
  const range = Array.isArray(event["xaxis.range"])
    ? event["xaxis.range"]
    : [event["xaxis.range[0]"], event["xaxis.range[1]"]];
  const [start, end] = range.map(Number);
  return Number.isFinite(start) && Number.isFinite(end) && start < end
    ? [start, end]
    : null;
}

function installHorizontalWheelControl() {
  if (state.interaction.horizontalWheelInstalled) {
    return;
  }
  state.interaction.horizontalWheelInstalled = true;
  document.addEventListener(
    "wheel",
    (event) => {
      if (
        !elements.plot.contains(event.target) ||
        Math.abs(event.deltaX) <= Math.abs(event.deltaY)
      ) {
        return;
      }

      // Horizontal trackpad input is emitted as wheel events. Intercept it
      // before Plotly's wheel handler so Start stays fixed and only End moves.
      event.preventDefault();
      event.stopPropagation();
      const currentRange = activeRangeOrFullRange();
      const plotWidth = elements.plot._fullLayout?._size?.w;
      const [rangeStart, rangeEnd] = rangeEndFromDrag(
        currentRange,
        event.deltaX,
        plotWidth,
      );
      if (
        Number(elements.rangeStart.value) === rangeStart &&
        Number(elements.rangeEnd.value) === rangeEnd
      ) {
        return;
      }

      elements.rangeStart.value = rangeStart;
      elements.rangeEnd.value = rangeEnd;
      renderPlot();
    },
    { capture: true, passive: false },
  );
}

function applyViewport(range) {
  return Plotly.relayout(elements.plot, {
    "xaxis.autorange": false,
    "xaxis.range": range,
  });
}

function saveViewerPreferences({
  range = state.persistedRange ?? activeRangeOrFullRange(),
  channels = state.persistedChannels,
  invertedSides = state.invertedSides,
} = {}) {
  try {
    const [fullStart, fullEnd] = state.fullRange;
    if (!Number.isFinite(fullStart) || !Number.isFinite(fullEnd)) {
      return;
    }

    let [rangeStart, rangeEnd] = range;
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

    const selectedChannels = [...channels].filter((channel) =>
      state.channels.includes(channel),
    );
    const payload = {
      version: VIEWER_PREFS_SCHEMA_VERSION,
      rangeStart,
      rangeEnd,
      selectedChannels,
      invertedSides: {
        right: Boolean(invertedSides.right),
        left: Boolean(invertedSides.left),
      },
    };
    localStorage.setItem(VIEWER_PREFS_STORAGE_KEY, JSON.stringify(payload));
    state.persistedRange = [rangeStart, rangeEnd];
    state.persistedChannels = new Set(selectedChannels);
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
    // 3) restore side inversion only from explicit booleans
    // 4) if restored values cannot produce a usable state, fall back to defaults
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

    return {
      selectedChannels,
      rangeStart,
      rangeEnd,
      invertedSides: {
        right: parsed.invertedSides?.right === true,
        left: parsed.invertedSides?.left === true,
      },
    };
  } catch {
    return null;
  }
}

function restorePersistedRange() {
  if (!state.persistedRange) {
    elements.status.classList.add("error");
    elements.status.textContent = "No persisted range found yet.";
    return;
  }

  elements.status.classList.remove("error");
  const persistedRange = [...state.persistedRange];
  [elements.rangeStart.value, elements.rangeEnd.value] = persistedRange;

  // Plotly can retain a panned axis through react(), so reset the primary
  // matched x-axis explicitly after that render has finished.
  Promise.resolve(renderPlot()).then(() => applyViewport(persistedRange));
}

function restorePersistedChannels() {
  if (state.persistedChannels.size === 0) {
    elements.status.classList.add("error");
    elements.status.textContent = "No persisted channel selection found yet.";
    return;
  }

  // Reset flow keeps temporary exploration reversible:
  // 1) hydrate persisted channels
  // 2) refresh checkbox UI
  // 3) re-render plot using current range inputs
  elements.status.classList.remove("error");
  state.selectedChannels = new Set(state.persistedChannels);
  renderChannelList();
  renderPlot();
}

function showRangeError(message) {
  elements.status.textContent = message;
  elements.status.classList.add("error");
}

function plotHeightFor(selectedCount) {
  const compactHeight = selectedCount * COMPACT_SUBPLOT_HEIGHT;
  if (window.innerWidth <= MOBILE_LAYOUT_MAX_WIDTH) {
    return Math.max(MOBILE_PLOT_MIN_HEIGHT, compactHeight);
  }
  return Math.max(elements.plotPanel.clientHeight, compactHeight);
}

function schedulePlotHeightUpdate() {
  if (state.plotResizeFrame !== null) {
    return;
  }

  // Resize flow:
  // 1) Wait until the panel has its new CSS dimensions.
  // 2) Recalculate only the Plotly height, preserving axes and interactions.
  // 3) Skip relayout when the compact height has not changed.
  state.plotResizeFrame = requestAnimationFrame(() => {
    state.plotResizeFrame = null;
    if (state.selectedChannels.size === 0) {
      return;
    }

    const plotHeight = plotHeightFor(state.selectedChannels.size);
    if (plotHeight === state.plotHeight) {
      return;
    }
    state.plotHeight = plotHeight;
    Plotly.relayout(elements.plot, { height: plotHeight });
  });
}

function renderPlot() {
  const selected = state.channels.filter((channel) =>
    state.selectedChannels.has(channel),
  );
  elements.emptyState.hidden = selected.length > 0;
  elements.plot.hidden = selected.length === 0;
  if (selected.length === 0) {
    state.plotHeight = null;
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
  syncEndRangeSlider();

  elements.status.classList.remove("error");
  elements.status.textContent = `${state.rows.length.toLocaleString()} samples · ${selected.length} subplot${selected.length === 1 ? "" : "s"}`;
  // Keep the full recording in every trace. The selected Start/End values
  // configure only the x-axis viewport, so later pan/zoom can reveal any FID.
  const dataRows = state.rows;

  // Give every trace its own y-axis domain while matching all x-axes to the
  // first one. The final subplot alone renders x tick labels, producing stacked
  // independent scales with synchronized zoom, pan, and hover positioning.
  const plotHeight = plotHeightFor(selected.length);
  state.plotHeight = plotHeight;
  const colorsByChannel = colorsForSelectedChannels(state.selectedChannels);
  const yAxisRanges = pairedYAxisRanges(selected, dataRows);
  const layout = {
    paper_bgcolor: "#111827",
    plot_bgcolor: "#111827",
    font: { color: "#c9d5e5", size: 11 },
    height: plotHeight,
    margin: { l: 55, r: 24, t: 28, b: 55 },
    hovermode: "x unified",
    showlegend: false,
    uirevision: `${range[0]}:${range[1]}:${selected.join("|")}:${state.invertedSides.right}:${state.invertedSides.left}`,
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
    const yAxisReference = `y${axisSuffix}`;
    const yAxisRange = yAxisRanges.get(channel);

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
      ...(yAxisRange ? { autorange: false, range: yAxisRange } : {}),
      gridcolor: "#263348",
      zerolinecolor: "#3b4d68",
      automargin: true,
    };
    subplotMeta.push({
      yAxisRef: yAxisReference,
      domainTop,
      domainHeight: domainTop - Math.max(0, domainBottom),
    });

    return {
      type: "scattergl",
      mode: "lines",
      name: channelLabel(channel),
      x: dataRows.map((row) => row.fid),
      y: dataRows.map((row) => displayedChannelValue(row, channel)),
      xaxis: `x${axisSuffix}`,
      yaxis: yAxisReference,
      connectgaps: false,
      line: { color: colorsByChannel.get(channel), width: 1.35 },
      hovertemplate: "%{y:.4f}<extra></extra>",
    };
  });
  const markerOverlay = buildMarkerOverlay(selected, subplotMeta, dataRows);
  layout.shapes = markerOverlay.shapes;
  layout.annotations = markerOverlay.annotations;

  const plotUpdate = Plotly.react(elements.plot, traces, layout, {
    responsive: true,
    displaylogo: false,
    scrollZoom: true,
    modeBarButtonsToRemove: ["lasso2d", "select2d"],
  });
  schedulePlotHeightUpdate();
  installHorizontalWheelControl();

  elements.plot.removeAllListeners?.("plotly_relayout");
  elements.plot.removeAllListeners?.("plotly_click");
  elements.plot.on("plotly_relayout", (event) => {
    // Plotly may report a relayout range as indexed keys or an array. Mirror
    // either form in the inputs, but leave persistence to Range Apply.
    const relayoutRange = rangeFromRelayout(event);
    if (relayoutRange) {
      const [start, end] = relayoutRange;
      elements.rangeStart.value = Math.round(start);
      elements.rangeEnd.value = Math.round(end);
      syncEndRangeSlider();
    }
  });
  elements.plot.on("plotly_click", (event) => {
    const clickedFid = event?.points?.[0]?.x;
    const markerFid = normalizeMarkerFid(clickedFid, dataRows, range);
    if (!Number.isFinite(markerFid)) {
      return;
    }
    state.markers.blue = markerFid;
    renderPlot();
  });
  elements.plot.oncontextmenu = (event) => {
    const clickedFid = fidFromContextMenu(event);
    const markerFid = normalizeMarkerFid(clickedFid, dataRows, range);
    if (!Number.isFinite(markerFid)) {
      return;
    }
    event.preventDefault();
    state.markers.red = markerFid;
    renderPlot();
  };

  return plotUpdate;
}

function enableControls() {
  for (const control of [
    elements.rangeStart,
    elements.rangeEnd,
    elements.rangeEndSlider,
    elements.applyRange,
    elements.resetRange,
    elements.restoreRange,
    elements.invertRight,
    elements.invertLeft,
    elements.channelSearch,
    elements.selectAll,
    elements.clearAll,
    elements.applyChannels,
    elements.restoreChannels,
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
    state.persistedChannels = new Set(state.selectedChannels);
    state.invertedSides = restoredPreferences?.invertedSides ?? {
      right: false,
      left: false,
    };
    elements.invertRight.checked = state.invertedSides.right;
    elements.invertLeft.checked = state.invertedSides.left;

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
    state.persistedRange = [
      Number(elements.rangeStart.value),
      Number(elements.rangeEnd.value),
    ];
    enableControls();
    renderChannelList();
    renderPlot();
    saveViewerPreferences();
  } catch (error) {
    elements.status.textContent = `Unable to load viewer: ${error.message}`;
    elements.status.classList.add("error");
  }
}

elements.applyRange.addEventListener("click", () => {
  renderPlot();
  saveViewerPreferences({ range: activeRangeOrFullRange() });
});
elements.resetRange.addEventListener("click", () => {
  [elements.rangeStart.value, elements.rangeEnd.value] = state.fullRange;
  renderPlot();
});
elements.restoreRange.addEventListener("click", restorePersistedRange);
elements.rangeStart.addEventListener("input", syncEndRangeSlider);
elements.rangeEnd.addEventListener("input", syncEndRangeSlider);
elements.invertRight.addEventListener("change", () => {
  state.invertedSides.right = elements.invertRight.checked;
  renderPlot();
  saveViewerPreferences();
});
elements.invertLeft.addEventListener("change", () => {
  state.invertedSides.left = elements.invertLeft.checked;
  renderPlot();
  saveViewerPreferences();
});
elements.rangeEndSlider.addEventListener("input", () => {
  elements.rangeEnd.value = elements.rangeEndSlider.value;
  elements.rangeEndSliderValue.value = elements.rangeEndSlider.value;
});
elements.rangeEndSlider.addEventListener("change", () => {
  // Input previews the chosen endpoint; change fires when a drag is released
  // (or a keyboard adjustment is committed), which is when the plot updates.
  renderPlot();
});
elements.channelSearch.addEventListener("input", renderChannelList);
elements.selectAll.addEventListener("click", () => {
  for (const channel of filteredChannels()) {
    state.selectedChannels.add(channel);
  }
  renderChannelList();
  renderPlot();
});
elements.clearAll.addEventListener("click", () => {
  state.selectedChannels.clear();
  renderChannelList();
  renderPlot();
});
elements.applyChannels.addEventListener("click", () => {
  saveViewerPreferences({ channels: state.selectedChannels });
});
elements.restoreChannels.addEventListener("click", restorePersistedChannels);
window.addEventListener("resize", schedulePlotHeightUpdate);
new ResizeObserver(schedulePlotHeightUpdate).observe(elements.plotPanel);

loadData();
