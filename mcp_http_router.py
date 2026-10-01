"""
Standalone MCP HTTP / JSON-RPC 2.0 Router for FastAPI.
Provides full compatibility with Claude.ai Custom Connectors on serverless platforms (Vercel).
Supports:
  - initialize (with MCP Apps extension capability)
  - notifications/initialized
  - ping
  - tools/list (with _meta.ui.resourceUri for MCP Apps)
  - tools/call (with structuredContent and content fallback)
  - resources/list
  - resources/read (serves ui:// HTML widget with CSP metadata)
  - GET healthcheck & SSE probe
  - CORS preflight OPTIONS
"""

import json
import base64
import html as html_module
from typing import Any, Dict, Optional, Tuple
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from mcp_tools import VOICES, _generate_audio, _save_result
import os

router = APIRouter()

# ---------------------------------------------------------------------------
# MCP Apps: UI Resource Definition
# ---------------------------------------------------------------------------

UI_RESOURCE_URI = "ui://voiceover-studio/player"
UI_RESOURCE_MIME = "text/html;profile=mcp-app"

# The audio player widget HTML.
# Fully self-contained, no external runtime dependencies needed.
# Implements the official Model Context Protocol Apps (ext-apps) protocol:
#  - ui/initialize request to Host
#  - ui/notifications/initialized notification
#  - ui/notifications/size-changed notification via ResizeObserver
#  - ui/notifications/tool-result handler (reading structuredContent & content)
#  - Interactive waveform, play/pause, time display, speed toggle, instant download
PLAYER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"/>
<meta name="color-scheme" content="light dark"/>
<title>Voiceover Player</title>
<style>
:root {
  --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --bg-card: #ffffff;
  --border-card: #e5e3dc;
  --text-main: #1f1e1d;
  --text-muted: #6f6e69;
  --accent: #c15f3e;
  --accent-soft: rgba(193, 95, 62, 0.12);
  --accent-hover: #a84c2f;
  --wave-bar: #d5d3cc;
  --wave-bar-active: #c15f3e;
  --badge-bg: #f3f1ec;
  --badge-text: #454440;
  --btn-bg: #f0eee8;
  --btn-hover: #e5e2d9;
  --card-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg-card: #262524;
    --border-card: #3e3d39;
    --text-main: #f4f3ef;
    --text-muted: #a3a19b;
    --accent: #d97757;
    --accent-soft: rgba(217, 119, 87, 0.2);
    --accent-hover: #ea8c6c;
    --wave-bar: #4a4944;
    --wave-bar-active: #d97757;
    --badge-bg: #32312d;
    --badge-text: #d5d3cc;
    --btn-bg: #353430;
    --btn-hover: #45443e;
    --card-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
  }
}

[data-theme="dark"] {
  --bg-card: #262524;
  --border-card: #3e3d39;
  --text-main: #f4f3ef;
  --text-muted: #a3a19b;
  --accent: #d97757;
  --accent-soft: rgba(217, 119, 87, 0.2);
  --accent-hover: #ea8c6c;
  --wave-bar: #4a4944;
  --wave-bar-active: #d97757;
  --badge-bg: #32312d;
  --badge-text: #d5d3cc;
  --btn-bg: #353430;
  --btn-hover: #45443e;
}

[data-theme="light"] {
  --bg-card: #ffffff;
  --border-card: #e5e3dc;
  --text-main: #1f1e1d;
  --text-muted: #6f6e69;
  --accent: #c15f3e;
  --accent-soft: rgba(193, 95, 62, 0.12);
  --accent-hover: #a84c2f;
  --wave-bar: #d5d3cc;
  --wave-bar-active: #c15f3e;
  --badge-bg: #f3f1ec;
  --badge-text: #454440;
  --btn-bg: #f0eee8;
  --btn-hover: #e5e2d9;
}

*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

html, body {
  background: transparent;
  font-family: var(--font-family);
  color: var(--text-main);
  line-height: 1.4;
  padding: 0;
  margin: 0;
  overflow: visible;
  -webkit-font-smoothing: antialiased;
}

.player-card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 12px;
  padding: 14px 16px;
  box-shadow: var(--card-shadow);
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
  max-width: 100%;
  transition: all 0.2s ease;
}

/* Header */
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.voice-block {
  display: flex;
  align-items: center;
  gap: 10px;
}

.avatar-badge {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--accent-soft);
  color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.avatar-badge svg {
  width: 18px;
  height: 18px;
  fill: currentColor;
}

.voice-meta {
  display: flex;
  flex-direction: column;
}

.voice-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-main);
  display: flex;
  align-items: center;
  gap: 6px;
}

.voice-style {
  font-size: 11px;
  color: var(--text-muted);
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 500;
  padding: 3px 8px;
  border-radius: 12px;
  background: var(--badge-bg);
  color: var(--badge-text);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #27ae60;
  display: inline-block;
}

.status-dot.playing {
  background: var(--accent);
  animation: pulseDot 1s infinite alternate;
}

@keyframes pulseDot {
  0% { transform: scale(0.8); opacity: 0.6; }
  100% { transform: scale(1.3); opacity: 1; }
}

/* Player Controls */
.player-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--btn-bg);
  padding: 10px 14px;
  border-radius: 10px;
}

.play-btn {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: none;
  background: var(--accent);
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  transition: transform 0.15s ease, background-color 0.15s ease;
}

.play-btn:hover {
  background: var(--accent-hover);
  transform: scale(1.04);
}

.play-btn:active {
  transform: scale(0.96);
}

.play-btn svg {
  width: 18px;
  height: 18px;
  fill: currentColor;
}

/* Waveform Visualizer */
.waveform-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  cursor: pointer;
  padding: 4px 0;
  min-width: 0;
}

.waveform-bars {
  display: flex;
  align-items: center;
  gap: 2px;
  height: 28px;
  width: 100%;
}

.wave-bar {
  flex: 1;
  min-width: 2px;
  max-width: 4px;
  background: var(--wave-bar);
  border-radius: 2px;
  transition: height 0.15s ease, background-color 0.15s ease, transform 0.15s ease;
  transform-origin: bottom;
}

.wave-bar.active {
  background: var(--wave-bar-active);
}

.waveform-bars.is-playing .wave-bar.active {
  animation: barBounce 0.9s ease-in-out infinite alternate;
}
.waveform-bars.is-playing .wave-bar.active:nth-child(2n) {
  animation-duration: 0.7s;
  animation-delay: 0.1s;
}
.waveform-bars.is-playing .wave-bar.active:nth-child(3n) {
  animation-duration: 1.1s;
  animation-delay: 0.2s;
}

@keyframes barBounce {
  0% { transform: scaleY(0.7); }
  100% { transform: scaleY(1.3); }
}

.time-row {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--text-muted);
  font-feature-settings: "tnum";
  font-variant-numeric: tabular-nums;
}

.speed-toggle {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  color: var(--text-main);
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
  flex-shrink: 0;
}

.speed-toggle:hover {
  border-color: var(--accent);
  color: var(--accent);
}

/* Metadata pills */
.meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  font-size: 11px;
  color: var(--text-muted);
}

.meta-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.meta-pill svg {
  width: 12px;
  height: 12px;
  fill: currentColor;
  opacity: 0.7;
}

/* Actions footer */
.actions-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-top: 4px;
  border-top: 1px solid var(--border-card);
}

.btn-action {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 500;
  text-decoration: none;
  padding: 5px 10px;
  border-radius: 6px;
  background: var(--btn-bg);
  color: var(--text-main);
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-action:hover {
  background: var(--btn-hover);
  border-color: var(--border-card);
}

.btn-action.primary {
  background: var(--accent-soft);
  color: var(--accent);
}

.btn-action.primary:hover {
  background: var(--accent);
  color: #ffffff;
}

.btn-action svg {
  width: 13px;
  height: 13px;
  fill: currentColor;
}

/* Loading skeleton */
.skeleton-card {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: center;
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
}

.spinner {
  width: 24px;
  height: 24px;
  border: 2px solid var(--border-card);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.error-card {
  padding: 14px 16px;
  background: rgba(231, 76, 60, 0.08);
  border: 1px solid rgba(231, 76, 60, 0.25);
  border-radius: 10px;
  color: #e74c3c;
  font-size: 12px;
}
</style>
</head>
<body>
<div id="app">
  <div class="player-card">
    <div class="skeleton-card">
      <div class="spinner"></div>
      <div>Initializing Voiceover Studio Player...</div>
    </div>
  </div>
</div>

<script>
(function() {
  const PROTOCOL_VERSION = "2025-11-25";
  let audioEl = null;
  let isPlaying = false;
  let currentSpeedIdx = 0;
  const speeds = [1.0, 1.25, 1.5, 0.8];
  let currentResult = null;
  let nextReqId = 1;
  const pendingRequests = new Map();

  const voiceMeta = {
    Eleanor: { gender: "Female", style: "Warm, Narrative & Expressive" },
    Jasper: { gender: "Male", style: "Deep, Resonant & Grounded" },
    Ivy: { gender: "Female", style: "Energetic, Bright & Upbeat" },
    Oliver: { gender: "Male", style: "Calm, Professional & Clear" },
    Luna: { gender: "Female", style: "Gentle, Intimate & Balanced" },
    Ethan: { gender: "Male", style: "Energetic, Dynamic & Youthful" },
    Charlotte: { gender: "Female", style: "Polished, Sophisticated & Refined" },
    Rafael: { gender: "Male", style: "Warm, Charismatic & Smooth" }
  };

  // Static bar height profile (32 bars mimicking a voice phrase)
  const barHeights = [
    25, 40, 65, 30, 85, 95, 60, 75, 45, 70,
    90, 80, 55, 35, 65, 85, 100, 75, 50, 60,
    80, 90, 60, 40, 70, 85, 50, 35, 60, 75,
    45, 30
  ];

  // -------------------------------------------------------------------------
  // MCP Apps Host Messaging Transport
  // -------------------------------------------------------------------------

  function postToHost(msg) {
    try {
      window.parent.postMessage(msg, "*");
    } catch(e) {
      console.warn("[MCP Player] postMessage failed:", e);
    }
  }

  function sendNotification(method, params = {}) {
    postToHost({ jsonrpc: "2.0", method, params });
  }

  function sendRequest(method, params = {}) {
    const id = nextReqId++;
    postToHost({ jsonrpc: "2.0", id, method, params });
    return new Promise((resolve) => {
      pendingRequests.set(id, resolve);
    });
  }

  // Report size to Claude so the iframe expands to fit the widget
  function reportSize() {
    const root = document.getElementById("app") || document.body;
    const height = Math.max(root.scrollHeight, root.offsetHeight, document.documentElement.scrollHeight, 140);
    const width = Math.max(root.scrollWidth, root.offsetWidth, document.documentElement.scrollWidth, 300);

    sendNotification("ui/notifications/size-changed", {
      width: Math.round(width),
      height: Math.round(height)
    });

    sendNotification("size-changed", {
      width: Math.round(width),
      height: Math.round(height)
    });
  }

  // -------------------------------------------------------------------------
  // Handshake Initialization
  // -------------------------------------------------------------------------

  async function performHandshake() {
    // 1. Send ui/initialize request to Host
    try {
      await sendRequest("ui/initialize", {
        appCapabilities: {},
        protocolVersion: PROTOCOL_VERSION,
        appInfo: { name: "voiceover-player", version: "2.0.0" }
      });
    } catch(e) {}

    // 2. Send initialized notification
    sendNotification("ui/notifications/initialized", {});
    sendNotification("notifications/initialized", {});

    // 3. Report size immediately
    reportSize();
  }

  // -------------------------------------------------------------------------
  // Result Extraction & Parsing
  // -------------------------------------------------------------------------

  function extractResultData(raw) {
    if (!raw) return null;

    // Check if params has structuredContent
    if (raw.params && raw.params.structuredContent) {
      return raw.params.structuredContent;
    }
    // Check if params is itself the tool output
    if (raw.params && (raw.params.audio_url || raw.params.audio_data_url || raw.params.filename)) {
      return raw.params;
    }
    // Check if result has structuredContent
    if (raw.result && raw.result.structuredContent) {
      return raw.result.structuredContent;
    }
    // Check if result is itself the tool output
    if (raw.result && (raw.result.audio_url || raw.result.audio_data_url || raw.result.filename)) {
      return raw.result;
    }
    // Check content array in params or result
    const content = (raw.params && raw.params.content) || (raw.result && raw.result.content) || raw.content;
    if (Array.isArray(content)) {
      for (const item of content) {
        if (item && item.type === "text" && typeof item.text === "string") {
          try {
            const parsed = JSON.parse(item.text);
            if (parsed && (parsed.audio_url || parsed.audio_data_url || parsed.filename || parsed.success !== undefined)) {
              return parsed;
            }
          } catch(e) {}
        }
      }
    }
    // Check direct object
    if (raw.audio_url || raw.audio_data_url || raw.filename) {
      return raw;
    }

    return null;
  }

  // -------------------------------------------------------------------------
  // Message Listener
  // -------------------------------------------------------------------------

  window.addEventListener("message", function(event) {
    const data = event.data;
    if (!data) return;

    // Resolve any pending request promises
    if (data.id && pendingRequests.has(data.id)) {
      const resolver = pendingRequests.get(data.id);
      pendingRequests.delete(data.id);
      resolver(data.result);
    }

    // Host responds with hostContext (e.g. theme)
    if (data.result && data.result.hostContext) {
      if (data.result.hostContext.theme) {
        document.documentElement.setAttribute("data-theme", data.result.hostContext.theme);
      }
      reportSize();
    }

    // Host sends initialize request to View
    if (data.method === "ui/initialize" || data.method === "initialize") {
      postToHost({
        jsonrpc: "2.0",
        id: data.id,
        result: {
          protocolVersion: PROTOCOL_VERSION,
          capabilities: {},
          serverInfo: { name: "voiceover-player", version: "2.0.0" }
        }
      });
      sendNotification("ui/notifications/initialized", {});
      reportSize();
      return;
    }

    // Host sends theme update
    if (data.method === "ui/notifications/host-context-changed") {
      if (data.params && data.params.theme) {
        document.documentElement.setAttribute("data-theme", data.params.theme);
      }
      reportSize();
      return;
    }

    // Host sends tool result notification (ui/notifications/tool-result)
    if (data.method === "ui/notifications/tool-result" || data.method === "tool-result" || data.method === "ui/tool-result") {
      const toolData = extractResultData(data);
      if (toolData) {
        renderPlayer(toolData);
        return;
      }
    }

    // Fallback: check any message containing tool result data
    const toolData = extractResultData(data);
    if (toolData) {
      renderPlayer(toolData);
    }
  });

  // -------------------------------------------------------------------------
  // Render Player Card
  // -------------------------------------------------------------------------

  function formatTime(secs) {
    if (isNaN(secs) || secs < 0) return "0:00";
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return m + ":" + (s < 10 ? "0" : "") + s;
  }

  function escapeHtml(str) {
    const d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
  }

  function escapeAttr(str) {
    return String(str).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function renderPlayer(data) {
    if (!data) return;
    currentResult = data;

    if (data.error) {
      document.getElementById("app").innerHTML = `
        <div class="error-card">
          <strong>Voiceover Error:</strong> ${escapeHtml(data.message || "Synthesis failed")}
        </div>
      `;
      reportSize();
      return;
    }

    const voice = data.voice_id || "Voiceover";
    const metaInfo = voiceMeta[voice] || { gender: "", style: "Neural Kokoro Voice" };
    const words = data.word_count || 0;
    const segments = data.segment_count || 1;
    const fileSize = data.file_size_bytes;
    let sizeStr = "";
    if (fileSize) {
      sizeStr = fileSize > 1048576
        ? (fileSize / 1048576).toFixed(1) + " MB"
        : (fileSize / 1024).toFixed(0) + " KB";
    }

    const bitrate = (data.settings && data.settings.bitrate) || data.bitrate || "192k";

    // Audio source: prefer audio_data_url (base64 data URI) for zero-latency instant playback
    let audioSrc = data.audio_data_url || "";
    if (!audioSrc && data.audio_url) {
      const base = data._baseUrl || "";
      audioSrc = data.audio_url.startsWith("http") ? data.audio_url : (base + data.audio_url);
    }

    // Download URL
    let downloadHref = audioSrc;
    if (!downloadHref && data.download_url) {
      const base = data._baseUrl || "";
      downloadHref = data.download_url.startsWith("http") ? data.download_url : (base + data.download_url);
    }
    const filename = data.filename || "voiceover.mp3";

    // Build bars HTML
    const barsHtml = barHeights.map((h, i) =>
      `<div class="wave-bar" id="wb-${i}" style="height:${h}%;"></div>`
    ).join("");

    const app = document.getElementById("app");
    app.innerHTML = `
      <div class="player-card" id="player-container">
        <!-- Header -->
        <div class="card-header">
          <div class="voice-block">
            <div class="avatar-badge">
              <svg viewBox="0 0 24 24"><path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/><path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/></svg>
            </div>
            <div class="voice-meta">
              <div class="voice-name">
                ${escapeHtml(voice)}
                <span style="font-size:11px;font-weight:normal;opacity:0.75;">(${escapeHtml(metaInfo.gender || "AI")})</span>
              </div>
              <div class="voice-style">${escapeHtml(metaInfo.style)}</div>
            </div>
          </div>
          <div class="status-pill">
            <span class="status-dot" id="status-dot"></span>
            <span id="status-text">Ready</span>
          </div>
        </div>

        <!-- Controls & Waveform -->
        <div class="player-controls">
          <button class="play-btn" id="play-btn" aria-label="Play voiceover">
            <svg id="icon-play" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
            <svg id="icon-pause" viewBox="0 0 24 24" style="display:none;"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
          </button>

          <div class="waveform-container" id="waveform-click">
            <div class="waveform-bars" id="waveform-bars">
              ${barsHtml}
            </div>
            <div class="time-row">
              <span id="time-current">0:00</span>
              <span id="time-total">--:--</span>
            </div>
          </div>

          <button class="speed-toggle" id="speed-btn" title="Playback speed">1.0x</button>
        </div>

        <!-- Metadata Pills -->
        <div class="meta-row">
          <span class="meta-pill">
            <svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zM6 20V4h7v5h5v11H6z"/></svg>
            ${words} words
          </span>
          <span class="meta-pill">
            <svg viewBox="0 0 24 24"><path d="M3 4h18v2H3V4zm0 7h12v2H3v-2zm0 7h18v2H3v-2z"/></svg>
            ${segments} segment${segments !== 1 ? 's' : ''}
          </span>
          <span class="meta-pill">
            <svg viewBox="0 0 24 24"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg>
            ${escapeHtml(bitrate)}
          </span>
          ${sizeStr ? `
          <span class="meta-pill">
            <svg viewBox="0 0 24 24"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
            ${sizeStr}
          </span>` : ""}
        </div>

        <!-- Footer Actions -->
        <div class="actions-row">
          <a class="btn-action primary" id="download-btn" href="${escapeAttr(downloadHref)}" download="${escapeAttr(filename)}" target="_blank" rel="noopener">
            <svg viewBox="0 0 24 24"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
            <span>Download MP3</span>
          </a>
          <button class="btn-action" id="replay-btn" title="Replay from start">
            <svg viewBox="0 0 24 24"><path d="M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"/></svg>
            <span>Replay</span>
          </button>
        </div>

        <audio id="native-audio" src="${escapeAttr(audioSrc)}" preload="auto" playsinline></audio>
      </div>
    `;

    // Wire elements
    audioEl = document.getElementById("native-audio");
    const playBtn = document.getElementById("play-btn");
    const iconPlay = document.getElementById("icon-play");
    const iconPause = document.getElementById("icon-pause");
    const statusDot = document.getElementById("status-dot");
    const statusText = document.getElementById("status-text");
    const timeCurrent = document.getElementById("time-current");
    const timeTotal = document.getElementById("time-total");
    const speedBtn = document.getElementById("speed-btn");
    const replayBtn = document.getElementById("replay-btn");
    const waveformClick = document.getElementById("waveform-click");
    const waveformBars = document.getElementById("waveform-bars");

    function updatePlayState(playing) {
      isPlaying = playing;
      if (playing) {
        iconPlay.style.display = "none";
        iconPause.style.display = "block";
        statusDot.classList.add("playing");
        statusText.textContent = "Playing";
        waveformBars.classList.add("is-playing");
      } else {
        iconPlay.style.display = "block";
        iconPause.style.display = "none";
        statusDot.classList.remove("playing");
        statusText.textContent = audioEl.currentTime >= (audioEl.duration || 1) ? "Finished" : "Paused";
        waveformBars.classList.remove("is-playing");
      }
    }

    playBtn.onclick = function() {
      if (!audioEl) return;
      if (audioEl.paused) {
        audioEl.play().catch(e => console.warn("Audio play blocked:", e));
      } else {
        audioEl.pause();
      }
    };

    replayBtn.onclick = function() {
      if (!audioEl) return;
      audioEl.currentTime = 0;
      audioEl.play().catch(e => console.warn("Audio play blocked:", e));
    };

    speedBtn.onclick = function() {
      currentSpeedIdx = (currentSpeedIdx + 1) % speeds.length;
      const spd = speeds[currentSpeedIdx];
      if (audioEl) audioEl.playbackRate = spd;
      speedBtn.textContent = spd.toFixed(spd % 1 === 0 ? 1 : 2) + "x";
    };

    waveformClick.onclick = function(e) {
      if (!audioEl || !audioEl.duration || isNaN(audioEl.duration)) return;
      const rect = waveformClick.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const pct = Math.max(0, Math.min(1, clickX / rect.width));
      audioEl.currentTime = pct * audioEl.duration;
      updateProgress();
    };

    function updateProgress() {
      if (!audioEl) return;
      const cur = audioEl.currentTime || 0;
      const dur = audioEl.duration || 0;
      timeCurrent.textContent = formatTime(cur);
      if (dur > 0 && !isNaN(dur)) {
        timeTotal.textContent = formatTime(dur);
        const activeCount = Math.floor((cur / dur) * barHeights.length);
        for (let i = 0; i < barHeights.length; i++) {
          const bar = document.getElementById("wb-" + i);
          if (bar) {
            if (i <= activeCount) {
              bar.classList.add("active");
            } else {
              bar.classList.remove("active");
            }
          }
        }
      }
    }

    audioEl.addEventListener("loadedmetadata", function() {
      if (audioEl.duration && !isNaN(audioEl.duration)) {
        timeTotal.textContent = formatTime(audioEl.duration);
      }
      reportSize();
    });

    audioEl.addEventListener("timeupdate", updateProgress);
    audioEl.addEventListener("play", () => updatePlayState(true));
    audioEl.addEventListener("pause", () => updatePlayState(false));
    audioEl.addEventListener("ended", () => {
      updatePlayState(false);
      statusText.textContent = "Finished";
    });

    reportSize();
  }

  // -------------------------------------------------------------------------
  // Setup observers & initiate
  // -------------------------------------------------------------------------

  // ResizeObserver to automatically notify host of height updates
  if (window.ResizeObserver) {
    const ro = new ResizeObserver(() => reportSize());
    ro.observe(document.body);
  }
  window.addEventListener("resize", reportSize);
  window.addEventListener("load", reportSize);

  // Check query params if data was passed in URL
  try {
    const params = new URLSearchParams(window.location.search);
    const dataStr = params.get("data");
    if (dataStr) {
      renderPlayer(JSON.parse(decodeURIComponent(dataStr)));
    }
  } catch(e) {}

  // Run initial protocol handshake
  performHandshake();

})();
</script>
</body>
</html>"""

# ---------------------------------------------------------------------------
# UI Resource list entry (for resources/list)
# ---------------------------------------------------------------------------
UI_RESOURCES = [
    {
        "uri": UI_RESOURCE_URI,
        "name": "Voiceover Audio Player",
        "description": "Interactive audio player widget that renders inline after voiceover generation.",
        "mimeType": UI_RESOURCE_MIME,
    }
]

# ---------------------------------------------------------------------------
# Tool Definitions (with MCP Apps metadata on generate_voiceover)
# ---------------------------------------------------------------------------

TOOLS_SPEC = [
    {
        "name": "list_voices",
        "description": (
            "List all available Kokoro TTS voices with their gender, style, and "
            "recommended use cases. Call this to choose the best voice for a script "
            "before calling generate_voiceover."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "generate_voiceover",
        "description": (
            "Generate a voiceover MP3 from script text using neural AI voices (Kokoro TTS). "
            "Saves the MP3 and returns download and playback metadata.\n\n"
            "INSTRUCTIONS FOR CLAUDE:\n"
            "Analyze the script tone and choose the best voice:\n"
            "- Storytelling / narrative -> Eleanor (Female) or Oliver (Male)\n"
            "- Documentary / thriller -> Charlotte (Female) or Jasper (Male)\n"
            "- Commercial / energetic -> Ivy (Female) or Ethan (Male)\n"
            "- Meditation / calm -> Luna (Female)\n"
            "- Charismatic / travel -> Rafael (Male)\n"
            "Keep speed at 0.0 (normal) and pitch at 1.0 unless a subtle adjustment fits."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Script text to synthesize. Supports paragraph breaks and pause markers like [pause: 1.2s], [beat].",
                },
                "voice_id": {
                    "type": "string",
                    "description": "Kokoro TTS voice: Eleanor, Jasper, Ivy, Oliver, Luna, Ethan, Charlotte, Rafael.",
                    "default": "Eleanor",
                },
                "speed": {
                    "type": "number",
                    "description": "Speed pacing: -1.0 to 1.0 (0.0 is normal).",
                    "default": 0.0,
                },
                "pitch": {
                    "type": "number",
                    "description": "Pitch factor: 0.5 to 1.5 (1.0 is default).",
                    "default": 1.0,
                },
                "bitrate": {
                    "type": "string",
                    "description": "Audio bitrate: 128k, 192k, 256k, 320k.",
                    "default": "192k",
                },
                "paragraph_pause": {
                    "type": "number",
                    "description": "Silence in seconds between paragraphs (0.0 to 3.0).",
                    "default": 0.8,
                },
                "smart_pacing": {
                    "type": "boolean",
                    "description": "Enable paragraph-aware silence stitching.",
                    "default": True,
                },
            },
            "required": ["text"],
            "additionalProperties": False,
        },
        # MCP Apps: link this tool to the audio player UI resource
        "_meta": {
            "ui": {
                "resourceUri": UI_RESOURCE_URI,
            },
            "ui/resourceUri": UI_RESOURCE_URI,
        },
    },
]


def execute_tool(name: str, args: Dict[str, Any], request: Optional[Request] = None) -> Tuple[Dict[str, Any], str]:
    """
    Executes an MCP tool and returns a tuple of:
      (result_dict, text_summary)
    where result_dict is delivered to MCP Apps via structuredContent,
    and text_summary is delivered via standard content[0].text fallback.
    """
    if name == "list_voices":
        return {"voices": VOICES}, json.dumps(VOICES, indent=2)

    if name == "generate_voiceover":
        api_key = os.environ.get("UNREALSPEECH_API_KEY", "").strip()
        if not api_key:
            err = {
                "error": True,
                "message": "UNREALSPEECH_API_KEY environment variable is not configured on the server."
            }
            return err, json.dumps(err)

        text = args.get("text", "")
        voice_id = args.get("voice_id", "Eleanor")
        speed = float(args.get("speed", 0.0))
        pitch = float(args.get("pitch", 1.0))
        bitrate = str(args.get("bitrate", "192k"))
        paragraph_pause = float(args.get("paragraph_pause", 0.8))
        smart_pacing = bool(args.get("smart_pacing", True))

        try:
            audio_bytes, segment_count, total_words = _generate_audio(
                text=text,
                voice_id=voice_id,
                speed=speed,
                pitch=pitch,
                bitrate=bitrate,
                paragraph_pause=paragraph_pause,
                smart_pacing=smart_pacing,
                api_key=api_key,
            )
        except Exception as e:
            err = {"error": True, "message": f"Synthesis error: {str(e)}"}
            return err, json.dumps(err)

        meta = _save_result(
            audio_bytes=audio_bytes,
            voice_id=voice_id,
            speed=speed,
            pitch=pitch,
            bitrate=bitrate,
            paragraph_pause=paragraph_pause,
            smart_pacing=smart_pacing,
            original_text=text.strip(),
            segment_count=segment_count,
            total_words=total_words,
        )

        # Determine public base URL dynamically from request headers or environment
        base_url = ""
        if request is not None:
            proto = request.headers.get("x-forwarded-proto", "https")
            host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
            if host:
                base_url = f"{proto}://{host}"
        if not base_url:
            v_url = os.environ.get("VERCEL_URL", "")
            if v_url:
                base_url = v_url if v_url.startswith("http") else f"https://{v_url}"

        filename = meta.get("filename", "")
        # Use /api paths so Vercel forwards requests directly to the serverless function
        download_path = f"/api/download/{filename}"
        audio_path = f"/api/outputs/{filename}"

        download_url = f"{base_url}{download_path}" if base_url else download_path
        audio_url = f"{base_url}{audio_path}" if base_url else audio_path

        result_dict = {
            "success": True,
            "filename": filename,
            "download_url": download_url,
            "audio_url": audio_url,
            "voice_id": voice_id,
            "word_count": total_words,
            "segment_count": segment_count,
            "file_size_bytes": meta.get("file_size_bytes", len(audio_bytes)),
            "_baseUrl": base_url,
            "settings": {
                "speed": speed,
                "pitch": pitch,
                "bitrate": bitrate,
                "paragraph_pause": paragraph_pause,
                "smart_pacing": smart_pacing,
            },
            "message": f"Voiceover generated successfully! ({total_words} words, voice: {voice_id})"
        }

        text_summary = json.dumps(result_dict, indent=2)
        return result_dict, text_summary

    raise ValueError(f"Unknown tool: {name}")


async def handle_mcp_request(body: Dict[str, Any], request: Optional[Request] = None) -> Dict[str, Any]:
    """Process a single JSON-RPC 2.0 MCP request."""
    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    if method == "initialize":
        ui_extension = {
            "version": "0.1.0"
        }
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {
                        "listChanged": False
                    },
                    "resources": {
                        "subscribe": False,
                        "listChanged": False,
                    },
                    "extensions": {
                        "io.modelcontextprotocol/ui": ui_extension
                    }
                },
                "extensions": {
                    "io.modelcontextprotocol/ui": ui_extension
                },
                "serverInfo": {
                    "name": "voiceover-studio",
                    "version": "2.0.0"
                },
            }
        }

    if method in ("notifications/initialized", "initialized", "ui/notifications/initialized"):
        if req_id is not None:
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        return {"jsonrpc": "2.0", "result": {}}

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": TOOLS_SPEC
            }
        }

    if method == "resources/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "resources": UI_RESOURCES
            }
        }

    if method == "resources/read":
        uri = params.get("uri", "")
        if uri == UI_RESOURCE_URI:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "contents": [{
                        "uri": UI_RESOURCE_URI,
                        "mimeType": UI_RESOURCE_MIME,
                        "text": PLAYER_HTML,
                        "_meta": {
                            "ui": {
                                "prefersBorder": False,
                                "csp": {
                                    "resourceDomains": [
                                        "https://unpkg.com",
                                        "https://cdn.jsdelivr.net",
                                        "https://*.vercel.app",
                                        "https://*.unrealspeech.com",
                                        "http://localhost:*",
                                        "http://127.0.0.1:*"
                                    ],
                                    "connectDomains": [
                                        "https://*.vercel.app",
                                        "https://*.unrealspeech.com",
                                        "http://localhost:*",
                                        "http://127.0.0.1:*"
                                    ]
                                }
                            }
                        }
                    }]
                }
            }
        # Unknown resource
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32602,
                "message": f"Resource not found: {uri}"
            }
        }

    if method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments") or {}
        try:
            result_data, output_text = execute_tool(tool_name, tool_args, request=request)
            is_error = bool(result_data.get("error"))
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": output_text
                        }
                    ],
                    "structuredContent": result_data,
                    "isError": is_error
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Error: {str(e)}"
                        }
                    ],
                    "structuredContent": {"error": True, "message": str(e)},
                    "isError": True
                }
            }

    # Unsupported method
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32601,
            "message": f"Method '{method}' not found"
        }
    }


@router.get("/mcp")
@router.get("/api/mcp")
async def mcp_get_handler(request: Request):
    """
    Handle GET requests from Claude connector probes, health checks, or SSE requests.
    """
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
        body = "event: endpoint\ndata: /mcp\n\n"
        return Response(content=body, media_type="text/event-stream", headers=headers)

    # Standard JSON health check
    return JSONResponse({
        "status": "ok",
        "name": "voiceover-studio",
        "protocolVersion": "2024-11-05",
        "transport": "streamable-http",
        "tools": [t["name"] for t in TOOLS_SPEC],
        "resources": [r["uri"] for r in UI_RESOURCES],
        "extensions": ["io.modelcontextprotocol/ui"],
    })


@router.post("/mcp")
@router.post("/api/mcp")
async def mcp_post_handler(request: Request):
    """
    Main MCP JSON-RPC 2.0 endpoint for Claude connector.
    """
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}
        )

    # Handle batch or single request
    if isinstance(data, list):
        results = [await handle_mcp_request(item, request=request) for item in data]
        return JSONResponse(results)

    result = await handle_mcp_request(data, request=request)
    return JSONResponse(result)


@router.options("/mcp")
@router.options("/api/mcp")
async def mcp_options_handler():
    """CORS preflight handler."""
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, x-api-key",
        }
    )
