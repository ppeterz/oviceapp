/**
 * O-Voice Studio - Web Application Controller
 * Handles dual speech engines (Browser Web Speech & Unreal Speech Neural AI),
 * real-time waveform visualizer, synchronized teleprompter, presets, and audio export.
 */

// ============================================================================
// CONSTANTS & SAMPLE SCRIPTS
// ============================================================================

const SAMPLE_SCRIPTS = {
  storytelling: `The old clockmaker in Prague had spent forty-two years calibrating the gears of the astronomical tower. Every evening at seven, he wound the brass escapement with a heavy iron key that bore his grandfather's initials. Legend said that if the clock ever stopped ticking, the river below would reverse its course. On a bitter Tuesday in November, the pendulum swung... and hesitated.`,

  curious: `Have you ever wondered what the deepest trenches of our oceans actually sound like? Far beneath the reach of sunlight, three miles down into the Mariana Trench, the water is not silent. Hydrophones lowered into the abyss recently captured a series of rhythmic metallic pulses echoing across the seafloor. Marine biologists are still debating whether the source is geothermal fissures... or something alive.`,

  mysterious: `The iron gates of the Blackwood Observatory had been chained shut since the winter of 1974. Yet every equinox, the copper dome on the hill slowly rotates toward the constellation Cygnus. Nobody has lived inside for half a century. But if you stand beneath the pines at three in the morning, you can distinctly hear the hum of a telescope cooling down.`,

  commercial: `Introducing the Apex Wireless Studio Pro. Engineered with custom beryllium acoustic drivers, intelligent four-tier active noise cancellation, and fifty hours of continuous hi-res battery life. Hear every breath, every bassline, every subtle inflection the way the artist mastered it. Elevate your sound today at apex-audio.com.`,

  meditation: `Close your eyes and let your shoulders release any tension they've been carrying today. Take a slow, deliberate breath in through your nose... hold it gently for a quiet moment... and release slowly through your mouth. Notice the space between your thoughts. There is nowhere else you need to be right now. Simply listen, and breathe.`
};

const PRESETS = {
  storytelling: {
    label: "Storytelling",
    voiceId: "Eleanor",
    pitch: 0.98,
    speed: -0.05,
    bitrate: "192k",
    tag: "Warm & Narrative"
  },
  curious: {
    label: "Curious",
    voiceId: "Ivy",
    pitch: 1.06,
    speed: 0.08,
    bitrate: "256k",
    tag: "Inquisitive & Dynamic"
  },
  mysterious: {
    label: "Slightly Mysterious",
    voiceId: "Jasper",
    pitch: 0.88,
    speed: -0.15,
    bitrate: "320k",
    tag: "Deep & Resonant"
  },
  commercial: {
    label: "Commercial Ad",
    voiceId: "Ethan",
    pitch: 1.05,
    speed: 0.15,
    bitrate: "192k",
    tag: "Punchy & Upbeat"
  },
  calm: {
    label: "Calm Meditation",
    voiceId: "Luna",
    pitch: 0.92,
    speed: -0.25,
    bitrate: "192k",
    tag: "Gentle & Soothing"
  },
  documentary: {
    label: "Documentary",
    voiceId: "Oliver",
    pitch: 0.95,
    speed: 0.00,
    bitrate: "256k",
    tag: "Authoritative & Clear"
  }
};

// ============================================================================
// APP STATE
// ============================================================================

const state = {
  engine: "neural", // "neural" or "browser"
  voiceId: "Eleanor",
  genderFilter: "all",
  pitch: 1.0,
  speed: 0.0,
  bitrate: "192k",
  volume: 1.0,
  isMuted: false,
  apiKey: localStorage.getItem("unrealspeech_api_key") || "",
  
  // Pacing & Cadence
  paragraphPause: 0.8,
  smartPacing: true,
  
  // Playback state
  isPlaying: false,
  isPaused: false,
  isGenerating: false,
  activeTakeUrl: null,
  activeFilename: null,
  
  // Teleprompter words & positions
  scriptText: "",
  wordsArray: [],
  currentWordIndex: -1,
  
  // Web Speech API
  browserVoices: [],
  selectedBrowserVoiceIndex: 0,
  speechSynthesisUtterance: null,
  browserSpeechTimeouts: [],
  
  // Audio Visualizer
  audioContext: null,
  analyserNode: null,
  audioSourceNode: null,
  visualizerAnimId: null,
};

// ============================================================================
// DOM ELEMENTS CACHE
// ============================================================================

const dom = {
  // Engine
  engineNeuralBtn: document.getElementById("engine-neural-btn"),
  engineBrowserBtn: document.getElementById("engine-browser-btn"),
  bitrateContainer: document.getElementById("bitrate-container"),
  browserVoicesWrapper: document.getElementById("browser-voices-wrapper"),
  browserVoicesSelect: document.getElementById("browser-voices-select"),

  // Presets
  presetsMenuBtn: document.getElementById("presets-menu-btn"),
  presetsDropdown: document.getElementById("presets-dropdown"),
  currentPresetLabel: document.getElementById("current-preset-label"),
  presetItems: document.querySelectorAll(".preset-item"),

  // Script Editor & Teleprompter
  viewEditorBtn: document.getElementById("view-editor-btn"),
  viewPrompterBtn: document.getElementById("view-prompter-btn"),
  editorContainer: document.getElementById("editor-container"),
  teleprompterContainer: document.getElementById("teleprompter-container"),
  teleprompterContent: document.getElementById("teleprompter-content"),
  prompterToEditorBtn: document.getElementById("prompter-to-editor-btn"),
  scriptInput: document.getElementById("script-input"),
  sampleScriptsSelect: document.getElementById("sample-scripts-select"),
  insertPauseShort: document.getElementById("insert-pause-short"),
  insertPauseLong: document.getElementById("insert-pause-long"),
  pasteClipboardBtn: document.getElementById("paste-clipboard-btn"),
  clearScriptBtn: document.getElementById("clear-script-btn"),

  // Telemetry
  wordCount: document.getElementById("word-count"),
  charCount: document.getElementById("char-count"),
  estDuration: document.getElementById("est-duration"),

  // Voices & Filters
  voiceCards: document.querySelectorAll(".voice-card"),
  voiceFilterBtns: document.querySelectorAll(".voice-filter-btn"),
  previewVoiceBtns: document.querySelectorAll(".preview-voice-btn"),

  // Acoustic Sliders
  pitchSlider: document.getElementById("pitch-slider"),
  pitchVal: document.getElementById("pitch-val"),
  pitchTag: document.getElementById("pitch-tag"),
  speedSlider: document.getElementById("speed-slider"),
  speedVal: document.getElementById("speed-val"),
  speedTag: document.getElementById("speed-tag"),
  volumeSlider: document.getElementById("volume-slider"),
  volumeVal: document.getElementById("volume-val"),
  volIcon: document.getElementById("vol-icon"),
  muteBtn: document.getElementById("mute-btn"),
  bitrateVal: document.getElementById("bitrate-val"),
  bitratePills: document.querySelectorAll(".bitrate-pill"),
  resetAcousticsBtn: document.getElementById("reset-acoustics-btn"),

  // Pacing & Cadence
  pauseSlider: document.getElementById("pause-slider"),
  pauseVal: document.getElementById("pause-val"),
  pauseTag: document.getElementById("pause-tag"),
  smartPacingToggle: document.getElementById("smart-pacing-toggle"),
  pacingContainer: document.getElementById("pacing-container"),
  formatPacingBtn: document.getElementById("format-pacing-btn"),

  // Transport & Audio Player
  remoteAudioPlayer: document.getElementById("remote-audio-player"),
  waveformCanvas: document.getElementById("waveform-canvas"),
  waveformPlaceholder: document.getElementById("waveform-placeholder"),
  currentTime: document.getElementById("current-time"),
  totalTime: document.getElementById("total-time"),
  transportPlayBtn: document.getElementById("transport-play-btn"),
  transportStopBtn: document.getElementById("transport-stop-btn"),
  transportReplayBtn: document.getElementById("transport-replay-btn"),
  playIcon: document.getElementById("play-icon"),
  pauseIcon: document.getElementById("pause-icon"),
  generateNeuralBtn: document.getElementById("generate-neural-btn"),
  generateBtnText: document.getElementById("generate-btn-text"),
  generateSpinner: document.getElementById("generate-spinner"),
  generateIcon: document.getElementById("generate-icon"),
  downloadAudioLink: document.getElementById("download-audio-link"),

  // Settings Modal
  openSettingsBtn: document.getElementById("open-settings-btn"),
  closeSettingsBtn: document.getElementById("close-settings-btn"),
  cancelSettingsBtn: document.getElementById("cancel-settings-btn"),
  saveSettingsBtn: document.getElementById("save-settings-btn"),
  settingsModal: document.getElementById("settings-modal"),
  settingsApiKeyInput: document.getElementById("settings-api-key-input"),
  toggleKeyVisibility: document.getElementById("toggle-key-visibility"),
  eyeOpenIcon: document.getElementById("eye-open-icon"),
  eyeClosedIcon: document.getElementById("eye-closed-icon"),
  testApiKeyBtn: document.getElementById("test-api-key-btn"),
  clearApiKeyBtn: document.getElementById("clear-api-key-btn"),
  testKeyFeedback: document.getElementById("test-key-feedback"),
  apiStatusDot: document.getElementById("api-status-dot"),
  apiStatusText: document.getElementById("api-status-text"),

  // Takes / History Drawer
  toggleHistoryBtn: document.getElementById("toggle-history-btn"),
  closeHistoryBtn: document.getElementById("close-history-btn"),
  historyDrawer: document.getElementById("history-drawer"),
  historyList: document.getElementById("history-list"),
  historyCountBadge: document.getElementById("history-count-badge"),
  historyTotalCount: document.getElementById("history-total-count"),
  refreshHistoryBtn: document.getElementById("refresh-history-btn"),

  // Toast Container
  toastContainer: document.getElementById("toast-container"),
};

// ============================================================================
// INITIALIZATION
// ============================================================================

window.addEventListener("DOMContentLoaded", () => {
  initApiStatus();
  initWebSpeechVoices();
  initVisualizerCanvas();
  bindEventListeners();
  loadSampleScript("curious"); // Start with a compelling default
  applyPreset("curious");
  selectVoice("Eleanor"); // Ensure default voice matches v8 API
  loadHistory();
  updateTelemetry();
  switchScriptView("edit"); // Explicitly ensure editable script view on boot
});

// ============================================================================
// EVENT LISTENERS BINDING
// ============================================================================

function bindEventListeners() {
  // Engine switcher
  dom.engineNeuralBtn.addEventListener("click", () => setEngine("neural"));
  dom.engineBrowserBtn.addEventListener("click", () => setEngine("browser"));

  // Presets popover
  dom.presetsMenuBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    dom.presetsDropdown.classList.toggle("hidden");
  });
  document.addEventListener("click", () => {
    dom.presetsDropdown.classList.add("hidden");
  });
  dom.presetItems.forEach(item => {
    item.addEventListener("click", (e) => {
      const presetKey = item.getAttribute("data-preset");
      if (presetKey && PRESETS[presetKey]) {
        applyPreset(presetKey);
        loadSampleScript(presetKey);
      }
      dom.presetsDropdown.classList.add("hidden");
    });
  });

  // Script views (Editor vs Prompter)
  dom.viewEditorBtn.addEventListener("click", () => switchScriptView("edit"));
  dom.viewPrompterBtn.addEventListener("click", () => switchScriptView("prompter"));

  // Clicking anywhere on teleprompter or its Edit badge switches immediately to Script Editor
  if (dom.teleprompterContainer) {
    dom.teleprompterContainer.addEventListener("click", () => {
      switchScriptView("edit");
      dom.scriptInput.focus();
    });
  }
  if (dom.prompterToEditorBtn) {
    dom.prompterToEditorBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      switchScriptView("edit");
      dom.scriptInput.focus();
    });
  }

  // Script text input & helpers
  dom.scriptInput.addEventListener("input", () => {
    updateTelemetry();
    renderTeleprompterTokens();
  });
  dom.sampleScriptsSelect.addEventListener("change", (e) => {
    if (e.target.value) {
      loadSampleScript(e.target.value);
    }
  });
  dom.insertPauseShort.addEventListener("click", () => insertTextAtCursor("[pause: 0.5s] "));
  dom.insertPauseLong.addEventListener("click", () => insertTextAtCursor("[pause: 1.0s] "));
  dom.pasteClipboardBtn.addEventListener("click", handlePasteClipboard);
  dom.clearScriptBtn.addEventListener("click", () => {
    if (dom.scriptInput.value.trim() && confirm("Clear script editor?")) {
      dom.scriptInput.value = "";
      updateTelemetry();
      renderTeleprompterTokens();
      showToast("Script cleared", "info");
    }
  });

  // Voice selection & audition
  dom.voiceCards.forEach(card => {
    card.addEventListener("click", (e) => {
      if (e.target.closest(".preview-voice-btn")) return;
      const voiceId = card.getAttribute("data-voice-id");
      selectVoice(voiceId);
    });
  });

  dom.previewVoiceBtns.forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const voiceId = btn.getAttribute("data-voice");
      auditionVoice(voiceId);
    });
  });

  // Voice gender filter
  dom.voiceFilterBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      dom.voiceFilterBtns.forEach(b => b.classList.remove("active", "text-amber-400", "bg-studio-800"));
      btn.classList.add("active", "text-amber-400", "bg-studio-800");
      filterVoices(btn.getAttribute("data-filter"));
    });
  });

  // Browser voices select
  dom.browserVoicesSelect.addEventListener("change", (e) => {
    state.selectedBrowserVoiceIndex = parseInt(e.target.value, 10);
  });

  // Acoustic Sliders
  dom.pitchSlider.addEventListener("input", handlePitchChange);
  dom.speedSlider.addEventListener("input", handleSpeedChange);
  dom.volumeSlider.addEventListener("input", handleVolumeChange);
  dom.muteBtn.addEventListener("click", toggleMute);
  dom.resetAcousticsBtn.addEventListener("click", resetAcoustics);

  // Pacing controls
  if (dom.pauseSlider) dom.pauseSlider.addEventListener("input", handlePauseChange);
  if (dom.smartPacingToggle) dom.smartPacingToggle.addEventListener("change", handleSmartPacingToggle);
  if (dom.formatPacingBtn) dom.formatPacingBtn.addEventListener("click", formatScriptForPacing);

  // Bitrate pills
  dom.bitratePills.forEach(pill => {
    pill.addEventListener("click", () => {
      dom.bitratePills.forEach(p => p.classList.remove("active", "bg-studio-800", "border-amber-500/40", "text-amber-400"));
      pill.classList.add("active", "bg-studio-800", "border-amber-500/40", "text-amber-400");
      state.bitrate = pill.getAttribute("data-bitrate");
      const labels = {
        "128k": "128 kbps (Compact)",
        "192k": "192 kbps (Standard)",
        "256k": "256 kbps (High Def)",
        "320k": "320 kbps (Studio Master)"
      };
      dom.bitrateVal.textContent = labels[state.bitrate] || state.bitrate;
    });
  });

  // Transport controls
  dom.transportPlayBtn.addEventListener("click", handleTogglePlay);
  dom.transportStopBtn.addEventListener("click", handleStopPlayback);
  dom.transportReplayBtn.addEventListener("click", handleRestartPlayback);
  dom.generateNeuralBtn.addEventListener("click", generateNeuralAudio);
  if (dom.downloadAudioLink) {
    dom.downloadAudioLink.addEventListener("click", (e) => {
      if (!state.activeFilename && !state.activeTakeUrl) {
        e.preventDefault();
        showToast("Please generate a Studio MP3 or select a take from History first.", "warning");
        return;
      }
      showToast(`Downloading ${state.activeFilename || "voiceover.mp3"}...`, "info");
      // Let the native anchor navigate to /api/download/... triggering native file attachment save
    });
  }

  // Settings modal
  dom.openSettingsBtn.addEventListener("click", openSettings);
  dom.closeSettingsBtn.addEventListener("click", closeSettings);
  dom.cancelSettingsBtn.addEventListener("click", closeSettings);
  dom.saveSettingsBtn.addEventListener("click", saveSettings);
  dom.toggleKeyVisibility.addEventListener("click", toggleKeyVisibility);
  dom.testApiKeyBtn.addEventListener("click", testApiKeyConnection);
  dom.clearApiKeyBtn.addEventListener("click", clearApiKey);

  // History Drawer
  dom.toggleHistoryBtn.addEventListener("click", toggleHistoryDrawer);
  dom.closeHistoryBtn.addEventListener("click", closeHistoryDrawer);
  dom.refreshHistoryBtn.addEventListener("click", loadHistory);

  // Keyboard Shortcuts
  window.addEventListener("keydown", handleGlobalKeydown);

  // Remote Audio Player Events
  dom.remoteAudioPlayer.addEventListener("timeupdate", handleAudioTimeUpdate);
  dom.remoteAudioPlayer.addEventListener("ended", handleAudioEnded);
  dom.remoteAudioPlayer.addEventListener("play", () => setPlayingUI(true));
  dom.remoteAudioPlayer.addEventListener("pause", () => {
    if (!dom.remoteAudioPlayer.ended) setPlayingUI(false);
  });
}

// ============================================================================
// ENGINE MANAGEMENT
// ============================================================================

function setEngine(engine) {
  state.engine = engine;
  if (engine === "neural") {
    dom.engineNeuralBtn.classList.add("active", "text-amber-400", "bg-studio-800", "border-amber-500/20");
    dom.engineBrowserBtn.classList.remove("active", "text-amber-400", "bg-studio-800", "border-amber-500/20");
    dom.engineBrowserBtn.classList.add("text-slate-400");
    
    dom.bitrateContainer.classList.remove("opacity-40", "pointer-events-none");
    dom.browserVoicesWrapper.classList.add("hidden");
    dom.generateNeuralBtn.classList.remove("hidden");
    showToast("Engine switched to Unreal Speech Neural AI", "info");
  } else {
    dom.engineBrowserBtn.classList.add("active", "text-amber-400", "bg-studio-800", "border-amber-500/20");
    dom.engineNeuralBtn.classList.remove("active", "text-amber-400", "bg-studio-800", "border-amber-500/20");
    dom.engineNeuralBtn.classList.add("text-slate-400");
    
    dom.bitrateContainer.classList.add("opacity-40", "pointer-events-none");
    dom.browserVoicesWrapper.classList.remove("hidden");
    showToast("Engine switched to Local Browser Speech (Zero Cost / Offline)", "info");
  }
}

// ============================================================================
// PRESETS & SAMPLE SCRIPTS
// ============================================================================

function applyPreset(presetKey) {
  const p = PRESETS[presetKey];
  if (!p) return;

  dom.currentPresetLabel.textContent = p.label;

  // Set Voice
  selectVoice(p.voiceId);

  // Set Pitch
  state.pitch = p.pitch;
  dom.pitchSlider.value = p.pitch;
  handlePitchChange();

  // Set Speed
  state.speed = p.speed;
  dom.speedSlider.value = p.speed;
  handleSpeedChange();

  // Set Bitrate
  if (p.bitrate) {
    dom.bitratePills.forEach(pill => {
      if (pill.getAttribute("data-bitrate") === p.bitrate) {
        pill.click();
      }
    });
  }

  showToast(`Applied preset: ${p.label} (${p.tag})`, "success");
}

function loadSampleScript(sampleKey) {
  const text = SAMPLE_SCRIPTS[sampleKey];
  if (text) {
    dom.scriptInput.value = text;
    updateTelemetry();
    renderTeleprompterTokens();
    switchScriptView("edit");
    dom.scriptInput.focus();
  }
}

function insertTextAtCursor(text) {
  switchScriptView("edit");
  const input = dom.scriptInput;
  const start = input.selectionStart;
  const end = input.selectionEnd;
  const val = input.value;
  input.value = val.substring(0, start) + text + val.substring(end);
  input.selectionStart = input.selectionEnd = start + text.length;
  input.focus();
  updateTelemetry();
  renderTeleprompterTokens();
}

async function handlePasteClipboard() {
  try {
    const text = await navigator.clipboard.readText();
    if (text) {
      insertTextAtCursor(text);
      showToast("Pasted script from clipboard", "info");
    }
  } catch (err) {
    showToast("Clipboard access denied. Press Ctrl+V directly into editor.", "error");
  }
}

// ============================================================================
// VOICE MANAGEMENT & AUDITION
// ============================================================================

function selectVoice(voiceId) {
  state.voiceId = voiceId;
  dom.voiceCards.forEach(c => {
    if (c.getAttribute("data-voice-id") === voiceId) {
      c.classList.add("active", "border-amber-500/50", "bg-studio-850/90");
      c.classList.remove("border-studio-800", "bg-studio-950/60");
    } else {
      c.classList.remove("active", "border-amber-500/50", "bg-studio-850/90");
      c.classList.add("border-studio-800", "bg-studio-950/60");
    }
  });
}

function filterVoices(gender) {
  state.genderFilter = gender;
  dom.voiceCards.forEach(card => {
    const cardGender = card.getAttribute("data-gender");
    if (gender === "all" || cardGender === gender) {
      card.classList.remove("hidden");
    } else {
      card.classList.add("hidden");
    }
  });
}

function auditionVoice(voiceId) {
  // Short audition phrase
  const samplePhrase = `Hello, I'm ${voiceId}. Ready to voice your next production.`;
  speakWithBrowserVoice(samplePhrase);
}

function initWebSpeechVoices() {
  if (!("speechSynthesis" in window)) {
    console.warn("Web Speech API not supported in this browser.");
    return;
  }

  const loadVoices = () => {
    state.browserVoices = window.speechSynthesis.getVoices();
    if (!state.browserVoices.length) return;

    dom.browserVoicesSelect.innerHTML = "";
    state.browserVoices.forEach((voice, idx) => {
      const opt = document.createElement("option");
      opt.value = idx;
      opt.textContent = `${voice.name} (${voice.lang})${voice.default ? " — Default" : ""}`;
      dom.browserVoicesSelect.appendChild(opt);
    });
  };

  loadVoices();
  window.speechSynthesis.onvoiceschanged = loadVoices;
}

// ============================================================================
// ACOUSTIC CONTROLS
// ============================================================================

function handlePitchChange() {
  const p = parseFloat(dom.pitchSlider.value);
  state.pitch = p;
  dom.pitchVal.textContent = p.toFixed(2) + "x";

  let tag = "Natural";
  if (p < 0.75) tag = "Deep Bass";
  else if (p < 0.95) tag = "Grounded";
  else if (p > 1.25) tag = "High Tone";
  else if (p > 1.05) tag = "Bright";
  dom.pitchTag.textContent = tag;
}

function handleSpeedChange() {
  const s = parseFloat(dom.speedSlider.value);
  state.speed = s;
  dom.speedVal.textContent = (s >= 0 ? "+" : "") + s.toFixed(2);

  let tag = "Normal";
  if (s <= -0.5) tag = "Very Slow";
  else if (s < -0.1) tag = "Deliberate";
  else if (s >= 0.5) tag = "Very Fast";
  else if (s > 0.1) tag = "Dynamic";
  dom.speedTag.textContent = tag;

  updateTelemetry();
}

function handleVolumeChange() {
  const v = parseInt(dom.volumeSlider.value, 10);
  state.volume = v / 100;
  dom.volumeVal.textContent = v + "%";
  dom.remoteAudioPlayer.volume = state.volume;

  if (v === 0) {
    state.isMuted = true;
    updateMuteIcon();
  } else if (state.isMuted) {
    state.isMuted = false;
    updateMuteIcon();
  }
}

function toggleMute() {
  state.isMuted = !state.isMuted;
  if (state.isMuted) {
    dom.remoteAudioPlayer.volume = 0;
    dom.volumeSlider.value = 0;
    dom.volumeVal.textContent = "0%";
  } else {
    state.volume = 1.0;
    dom.remoteAudioPlayer.volume = 1.0;
    dom.volumeSlider.value = 100;
    dom.volumeVal.textContent = "100%";
  }
  updateMuteIcon();
}

function updateMuteIcon() {
  if (state.isMuted) {
    dom.volIcon.innerHTML = `<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/>`;
  } else {
    dom.volIcon.innerHTML = `<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/>`;
  }
}

function resetAcoustics() {
  dom.pitchSlider.value = 1.0;
  handlePitchChange();
  dom.speedSlider.value = 0.0;
  handleSpeedChange();
  dom.volumeSlider.value = 100;
  handleVolumeChange();
  // Reset pacing
  if (dom.pauseSlider) {
    dom.pauseSlider.value = 0.8;
    handlePauseChange();
  }
  if (dom.smartPacingToggle) {
    dom.smartPacingToggle.checked = true;
    state.smartPacing = true;
  }
  showToast("Acoustic parameters reset to studio defaults", "info");
}

function handlePauseChange() {
  const p = parseFloat(dom.pauseSlider.value);
  state.paragraphPause = p;
  dom.pauseVal.textContent = p.toFixed(2) + "s";

  let tag = "Storytelling";
  if (p <= 0.3) tag = "Snappy";
  else if (p <= 0.5) tag = "Conversational";
  else if (p <= 0.9) tag = "Storytelling";
  else if (p <= 1.3) tag = "Dramatic Beat";
  else if (p <= 1.8) tag = "Cinematic";
  else tag = "Deep Breath";
  dom.pauseTag.textContent = tag;
}

function handleSmartPacingToggle() {
  state.smartPacing = dom.smartPacingToggle.checked;
  if (state.smartPacing) {
    showToast("Smart Structure Mode enabled — paragraphs will be paced with silence", "info");
  } else {
    showToast("Smart Structure Mode disabled — single-pass synthesis", "info");
  }
}

function formatScriptForPacing() {
  const input = dom.scriptInput;
  let text = input.value;
  if (!text.trim()) {
    showToast("No script to format", "warning");
    return;
  }

  // Normalize line endings
  text = text.replace(/\r\n/g, '\n');

  // Normalize double hyphens to em dashes with breathing space
  text = text.replace(/\s*--\s*/g, ' — ');

  // Normalize multiple dots to proper ellipsis
  text = text.replace(/\.{2,}/g, '...');

  // Ensure paragraphs end with proper punctuation
  const paragraphs = text.split(/\n\s*\n/);
  const formatted = paragraphs.map(p => {
    let trimmed = p.trim();
    if (!trimmed) return '';
    // Add terminating punctuation if missing
    if (!/[.!?…]$/.test(trimmed)) {
      trimmed += '.';
    }
    return trimmed;
  }).filter(Boolean).join('\n\n');

  input.value = formatted;
  updateTelemetry();
  renderTeleprompterTokens();
  showToast("Script formatted for optimal pacing & structure", "success");
}

// ============================================================================
// TELEMETRY & READING TIME ESTIMATION
// ============================================================================

function updateTelemetry() {
  const text = dom.scriptInput.value.trim();
  state.scriptText = text;

  const words = text ? text.split(/\s+/).filter(Boolean) : [];
  const wordCount = words.length;
  const charCount = text.length;

  dom.wordCount.textContent = wordCount;
  dom.charCount.textContent = charCount;

  if (charCount > 3000) {
    dom.charCount.classList.add("text-red-400");
  } else {
    dom.charCount.classList.remove("text-red-400");
  }

  // Standard narration is ~140 words per minute. Adjust dynamically by speed factor.
  // speed ranges from -1.0 to 1.0 (where 0.0 is 1.0x pace, -0.5 is 0.6x, +0.5 is 1.4x)
  const speedFactor = 1.0 + (state.speed * 0.45);
  const wordsPerMinute = Math.max(60, 140 * speedFactor);
  const totalSeconds = Math.round((wordCount / wordsPerMinute) * 60);

  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  dom.estDuration.textContent = `${mins}:${secs < 10 ? "0" : ""}${secs} min`;
}

// ============================================================================
// TELEPROMPTER VIEW & SYNCHRONIZED HIGHLIGHTING
// ============================================================================

function switchScriptView(view) {
  if (view === "prompter") {
    renderTeleprompterTokens();
    dom.editorContainer.classList.add("hidden");
    dom.teleprompterContainer.classList.remove("hidden");
    dom.viewPrompterBtn.classList.add("active", "bg-studio-800", "text-white");
    dom.viewPrompterBtn.classList.remove("text-slate-400");
    dom.viewEditorBtn.classList.remove("active", "bg-studio-800", "text-white");
    dom.viewEditorBtn.classList.add("text-slate-400");
  } else {
    dom.teleprompterContainer.classList.add("hidden");
    dom.editorContainer.classList.remove("hidden");
    dom.viewEditorBtn.classList.add("active", "bg-studio-800", "text-white");
    dom.viewEditorBtn.classList.remove("text-slate-400");
    dom.viewPrompterBtn.classList.remove("active", "bg-studio-800", "text-white");
    dom.viewPrompterBtn.classList.add("text-slate-400");
  }
}

function renderTeleprompterTokens() {
  const text = dom.scriptInput.value.trim();
  if (!text) {
    dom.teleprompterContent.innerHTML = `<span class="text-slate-600 italic">No script entered yet. Switch to Editor to write or paste your script.</span>`;
    state.wordsArray = [];
    return;
  }

  // Split into tokens preserving whitespace and pause tags
  const tokens = text.split(/(\s+)/);
  let wordIndex = 0;
  let html = "";
  state.wordsArray = [];

  tokens.forEach(token => {
    if (token.startsWith("[pause")) {
      html += `<span class="px-2 py-0.5 rounded bg-studio-800 text-amber-400 text-xs font-mono font-bold mx-1 select-none">${token}</span>`;
    } else if (/\S/.test(token)) {
      html += `<span class="teleprompter-word" data-word-idx="${wordIndex}">${escapeHtml(token)}</span>`;
      state.wordsArray.push({ index: wordIndex, word: token });
      wordIndex++;
    } else {
      html += token;
    }
  });

  dom.teleprompterContent.innerHTML = html;
}

function highlightTeleprompterWord(wordIdx) {
  if (state.currentWordIndex === wordIdx) return;
  state.currentWordIndex = wordIdx;

  const words = dom.teleprompterContent.querySelectorAll(".teleprompter-word");
  words.forEach(el => {
    const idx = parseInt(el.getAttribute("data-word-idx"), 10);
    if (idx === wordIdx) {
      el.classList.add("active-word");
      // Auto-scroll into view if in teleprompter mode
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    } else {
      el.classList.remove("active-word");
    }
  });
}

function clearTeleprompterHighlight() {
  state.currentWordIndex = -1;
  const words = dom.teleprompterContent.querySelectorAll(".teleprompter-word");
  words.forEach(el => el.classList.remove("active-word"));
}

// ============================================================================
// AUDIO PLAYBACK & SYNTHESIS HANDLERS
// ============================================================================

function handleTogglePlay() {
  const text = dom.scriptInput.value.trim();
  if (!text) {
    showToast("Please enter a script first", "warning");
    dom.scriptInput.focus();
    return;
  }

  // If already generating neural audio, ignore
  if (state.isGenerating) return;

  // If in browser mode OR neural mode without generated file yet:
  if (state.engine === "browser" || !state.activeTakeUrl) {
    if (state.isPlaying) {
      handlePausePlayback();
    } else {
      if (dom.viewPrompterBtn.classList.contains("active")) {
        switchScriptView("prompter");
      }
      speakWithBrowserVoice(text);
    }
  } else {
    // Neural mode with existing activeTakeUrl
    if (dom.remoteAudioPlayer.paused) {
      if (dom.viewPrompterBtn.classList.contains("active")) {
        switchScriptView("prompter");
      }
      dom.remoteAudioPlayer.play();
      setPlayingUI(true);
      startVisualizer();
    } else {
      dom.remoteAudioPlayer.pause();
      setPlayingUI(false);
      stopVisualizer();
    }
  }
}

function handlePausePlayback() {
  if (state.engine === "browser") {
    if (window.speechSynthesis && window.speechSynthesis.speaking) {
      window.speechSynthesis.pause();
      state.isPaused = true;
      setPlayingUI(false);
      stopVisualizer();
    }
  } else {
    dom.remoteAudioPlayer.pause();
    setPlayingUI(false);
    stopVisualizer();
  }
}

function handleStopPlayback() {
  if (window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
  dom.remoteAudioPlayer.pause();
  dom.remoteAudioPlayer.currentTime = 0;
  setPlayingUI(false);
  stopVisualizer();
  clearTeleprompterHighlight();
  dom.currentTime.textContent = "00:00";
  switchScriptView("edit");
}

function handleRestartPlayback() {
  handleStopPlayback();
  handleTogglePlay();
}

function setPlayingUI(playing) {
  state.isPlaying = playing;
  if (playing) {
    dom.playIcon.classList.add("hidden");
    dom.pauseIcon.classList.remove("hidden");
    dom.transportStopBtn.disabled = false;
    dom.waveformPlaceholder.classList.add("hidden");
    dom.transportPlayBtn.classList.add("ring-4", "ring-amber-500/30");
  } else {
    dom.playIcon.classList.remove("hidden");
    dom.pauseIcon.classList.add("hidden");
    dom.transportPlayBtn.classList.remove("ring-4", "ring-amber-500/30");
  }
}

// ============================================================================
// BROWSER SPEECH SYNTHESIS (WEB SPEECH API)
// ============================================================================

function speakWithBrowserVoice(text, overrideVoiceId = null) {
  if (!("speechSynthesis" in window)) {
    showToast("Web Speech API not supported in this browser.", "error");
    return;
  }

  // Cancel any ongoing speech and clear pending timeouts
  window.speechSynthesis.cancel();
  state.browserSpeechTimeouts.forEach(t => clearTimeout(t));
  state.browserSpeechTimeouts = [];

  // Choose voice
  let chosenVoice = null;
  if (state.browserVoices.length > 0) {
    if (overrideVoiceId) {
      const genderPreferred = ["Dan", "Will"].includes(overrideVoiceId) ? "male" : "female";
      chosenVoice = state.browserVoices.find(v => v.name.toLowerCase().includes(genderPreferred)) || state.browserVoices[0];
    } else if (state.engine === "browser" && dom.browserVoicesSelect.value !== "") {
      chosenVoice = state.browserVoices[state.selectedBrowserVoiceIndex];
    } else {
      chosenVoice = state.browserVoices[0];
    }
  }

  // If smart pacing is enabled, speak paragraph by paragraph with pauses
  if (state.smartPacing && !overrideVoiceId) {
    const pauseTagPattern = /\[(?:pause|break)[:\s]*[\d.]*s?\]|\((?:pause|break)[:\s]*[\d.]*s?\)|\[beat\]/gi;
    const paragraphs = text.split(/\n\s*\n/).map(p => p.trim()).filter(Boolean);

    if (paragraphs.length > 1) {
      speakParagraphSequence(paragraphs, chosenVoice, 0);
      return;
    }
  }

  // Single-pass speech (fallback)
  const cleanText = text.replace(/\[pause:\s*[\d.]+s\]/gi, "...").replace(/\[beat\]/gi, "...");
  const utterance = createUtterance(cleanText, chosenVoice, true);
  state.speechSynthesisUtterance = utterance;
  window.speechSynthesis.speak(utterance);
}

function speakParagraphSequence(paragraphs, voice, index) {
  if (index >= paragraphs.length) {
    setPlayingUI(false);
    stopVisualizer();
    clearTeleprompterHighlight();
    switchScriptView("edit");
    return;
  }

  const paraText = paragraphs[index].replace(/\[pause:\s*[\d.]+s\]/gi, "...").replace(/\[beat\]/gi, "...").trim();
  if (!paraText) {
    speakParagraphSequence(paragraphs, voice, index + 1);
    return;
  }

  const isLast = (index === paragraphs.length - 1);
  const utterance = createUtterance(paraText, voice, isLast);

  utterance.onend = () => {
    if (isLast) {
      setPlayingUI(false);
      stopVisualizer();
      clearTeleprompterHighlight();
      switchScriptView("edit");
    } else {
      // Pause between paragraphs then speak next
      const pauseMs = state.paragraphPause * 1000;
      const tid = setTimeout(() => {
        speakParagraphSequence(paragraphs, voice, index + 1);
      }, pauseMs);
      state.browserSpeechTimeouts.push(tid);
    }
  };

  state.speechSynthesisUtterance = utterance;
  window.speechSynthesis.speak(utterance);
}

function createUtterance(text, voice, isFinal) {
  const utterance = new SpeechSynthesisUtterance(text);

  // Configure pitch (Web Speech: 0.1 to 2.0)
  utterance.pitch = Math.min(2.0, Math.max(0.1, state.pitch));

  // Configure rate (mapping state.speed to 0.5–1.8)
  const rateMultiplier = 1.0 + (state.speed * 0.5);
  utterance.rate = Math.min(2.0, Math.max(0.5, rateMultiplier));

  utterance.volume = state.isMuted ? 0 : state.volume;

  if (voice) utterance.voice = voice;

  // Synchronized Karaoke Word Boundary Highlight
  utterance.onboundary = (event) => {
    if (event.name === "word" && state.wordsArray.length > 0) {
      const wordIdx = Math.min(state.currentWordIndex + 1, state.wordsArray.length - 1);
      highlightTeleprompterWord(wordIdx);
    }
  };

  utterance.onstart = () => {
    setPlayingUI(true);
    startVisualizer();
  };

  utterance.onerror = (e) => {
    console.error("SpeechSynthesis error:", e);
    setPlayingUI(false);
    stopVisualizer();
    clearTeleprompterHighlight();
    switchScriptView("edit");
  };

  return utterance;
}

// ============================================================================
// NEURAL SPEECH API GENERATION
// ============================================================================

async function generateNeuralAudio() {
  const text = dom.scriptInput.value.trim();
  if (!text) {
    showToast("Please enter a script to generate", "warning");
    dom.scriptInput.focus();
    return;
  }

  // With smart pacing, the parser handles segmenting long scripts
  if (!state.smartPacing && text.length > 3000) {
    showToast("Script exceeds 3000 characters limit. Enable Smart Structure Mode or shorten.", "error");
    return;
  }

  // Verify key exists
  const key = state.apiKey.trim();
  if (!key) {
    openSettings();
    showToast("Please enter your Unreal Speech API Key to generate studio audio", "warning");
    return;
  }

  // Set loading state
  state.isGenerating = true;
  dom.generateBtnText.textContent = "Synthesizing...";
  dom.generateSpinner.classList.remove("hidden");
  dom.generateIcon.classList.add("hidden");
  dom.generateNeuralBtn.disabled = true;

  try {
    const payload = {
      text: text,
      voice_id: state.voiceId,
      bitrate: state.bitrate,
      speed: state.speed,
      pitch: state.pitch,
      timestamp_type: "sentence",
      api_key: key,
      paragraph_pause: state.paragraphPause,
      smart_pacing: state.smartPacing
    };

    const resp = await fetch("/api/unrealspeech/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: "Generation failed" }));
      throw new Error(err.detail || `Server returned ${resp.status}`);
    }

    const data = await resp.json();
    setActiveTake(data.audio_data || data.audio_url, data.filename, data);
    saveClientTake(data);

    showToast(`Studio voiceover generated successfully! (${data.voice_id} - ${data.bitrate})`, "success");

    // Refresh history
    loadHistory();

    // Auto-play the generated audio (preserves editor view so user can keep editing)
    if (dom.viewPrompterBtn.classList.contains("active")) {
      switchScriptView("prompter");
    }
    dom.remoteAudioPlayer.play();

  } catch (err) {
    console.error("Generation error:", err);
    showToast(err.message, "error");
  } finally {
    state.isGenerating = false;
    dom.generateBtnText.textContent = "Generate Studio MP3";
    dom.generateSpinner.classList.add("hidden");
    dom.generateIcon.classList.remove("hidden");
    dom.generateNeuralBtn.disabled = false;
  }
}

// ============================================================================
// CLIENT TAKE STORAGE (OFFLINE & VERCEL RESILIENCE)
// ============================================================================

const CLIENT_TAKES_KEY = "ovoice_client_takes";

function getClientTakes() {
  try {
    const raw = localStorage.getItem(CLIENT_TAKES_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    return [];
  }
}

function saveClientTake(take) {
  if (!take || !take.id) return;
  try {
    const takes = getClientTakes();
    const filtered = takes.filter(t => t.id !== take.id);
    filtered.unshift({
      id: take.id,
      filename: take.filename,
      audio_url: take.audio_url,
      audio_data: take.audio_data,
      download_url: take.download_url,
      text: take.text,
      word_count: take.word_count,
      voice_id: take.voice_id,
      bitrate: take.bitrate,
      speed: take.speed,
      pitch: take.pitch,
      created_at: take.created_at,
      created_at_formatted: take.created_at_formatted,
      file_size_bytes: take.file_size_bytes
    });
    // Keep up to 10 latest takes in localStorage
    while (filtered.length > 10) {
      filtered.pop();
    }
    localStorage.setItem(CLIENT_TAKES_KEY, JSON.stringify(filtered));
  } catch (e) {
    console.warn("Storage quota warning - caching metadata without raw audio:", e);
    try {
      const fallbackTakes = getClientTakes().map(t => {
        const { audio_data, ...rest } = t;
        return rest;
      });
      localStorage.setItem(CLIENT_TAKES_KEY, JSON.stringify(fallbackTakes.slice(0, 10)));
    } catch (_) {}
  }
}

function deleteClientTake(id) {
  try {
    const takes = getClientTakes().filter(t => t.id !== id);
    localStorage.setItem(CLIENT_TAKES_KEY, JSON.stringify(takes));
  } catch (e) {}
}

// ============================================================================
// AUDIO DOWNLOAD & ACTIVE TAKE MANAGEMENT
// ============================================================================

function setActiveTake(audioUrl, filename, takeData) {
  if (!audioUrl) return;
  
  let safeFilename = filename || (audioUrl ? audioUrl.split("/").pop() : "voiceover.mp3");
  if (!safeFilename.toLowerCase().endsWith(".mp3")) {
    safeFilename += ".mp3";
  }
  state.activeFilename = safeFilename;

  // If audio is base64 data URI, convert to Blob URL for instant playback & seeking
  let playbackUrl = audioUrl;
  if (typeof audioUrl === "string" && audioUrl.startsWith("data:audio")) {
    try {
      const parts = audioUrl.split(",");
      const byteCharacters = atob(parts[1]);
      const byteNumbers = new Array(byteCharacters.length);
      for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i);
      }
      const byteArray = new Uint8Array(byteNumbers);
      const blob = new Blob([byteArray], { type: "audio/mpeg" });
      playbackUrl = URL.createObjectURL(blob);
    } catch (e) {
      console.warn("Could not create object URL from data URI, using directly:", e);
    }
  }

  state.activeTakeUrl = playbackUrl;
  dom.remoteAudioPlayer.src = playbackUrl;
  dom.remoteAudioPlayer.load();

  if (dom.downloadAudioLink) {
    if (playbackUrl.startsWith("blob:") || playbackUrl.startsWith("data:")) {
      dom.downloadAudioLink.href = playbackUrl;
    } else {
      dom.downloadAudioLink.href = `/api/download/${encodeURIComponent(safeFilename)}`;
    }
    dom.downloadAudioLink.setAttribute("download", safeFilename);
    dom.downloadAudioLink.classList.remove("opacity-40", "cursor-not-allowed", "pointer-events-none");
    dom.downloadAudioLink.classList.add(
      "opacity-100",
      "cursor-pointer",
      "bg-amber-500/20",
      "hover:bg-amber-500/30",
      "border-amber-500/50",
      "text-amber-300",
      "shadow-md",
      "shadow-amber-500/10",
      "active:scale-95"
    );
    dom.downloadAudioLink.title = `Download MP3 (${safeFilename})`;
    const textSpan = dom.downloadAudioLink.querySelector("span");
    if (textSpan) textSpan.textContent = "Download MP3";
  }
}

function downloadAudioFile(audioUrl, filename) {
  let actualFilename = filename || (audioUrl ? audioUrl.split("/").pop() : null) || state.activeFilename;

  if (!actualFilename || (!audioUrl && !state.activeTakeUrl)) {
    showToast("Please generate a Studio MP3 or select a take from History first.", "warning");
    return;
  }

  if (!actualFilename.toLowerCase().endsWith(".mp3")) {
    actualFilename += ".mp3";
  }

  showToast(`Downloading ${actualFilename}...`, "info");

  const downloadEndpoint = `/api/download/${encodeURIComponent(actualFilename)}`;

  // Direct trigger of attachment endpoint ensures Chrome and Windows
  // receive Content-Disposition: attachment; filename="take_...mp3"
  // so the file is saved with the proper .mp3 extension and music player association!
  const a = document.createElement("a");
  a.style.display = "none";
  a.href = downloadEndpoint;
  a.setAttribute("download", actualFilename);
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    document.body.removeChild(a);
  }, 1000);

  showToast(`MP3 file downloaded: ${actualFilename}`, "success");
}

function handleAudioTimeUpdate() {
  const current = dom.remoteAudioPlayer.currentTime;
  const duration = dom.remoteAudioPlayer.duration;

  if (!isNaN(current)) {
    const cM = Math.floor(current / 60);
    const cS = Math.floor(current % 60);
    dom.currentTime.textContent = `${cM < 10 ? "0" : ""}${cM}:${cS < 10 ? "0" : ""}${cS}`;
  }

  if (!isNaN(duration) && duration > 0) {
    const dM = Math.floor(duration / 60);
    const dS = Math.floor(duration % 60);
    dom.totalTime.textContent = `/ ${dM < 10 ? "0" : ""}${dM}:${dS < 10 ? "0" : ""}${dS}`;

    // Rough word tracking based on progress percentage
    if (state.wordsArray.length > 0) {
      const progress = current / duration;
      const wordIdx = Math.min(state.wordsArray.length - 1, Math.floor(progress * state.wordsArray.length));
      highlightTeleprompterWord(wordIdx);
    }
  }
}

function handleAudioEnded() {
  setPlayingUI(false);
  stopVisualizer();
  clearTeleprompterHighlight();
  switchScriptView("edit");
}

// ============================================================================
// AUDIO WAVEFORM CANVAS VISUALIZER
// ============================================================================

function initVisualizerCanvas() {
  const canvas = dom.waveformCanvas;
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = (rect.width || 340) * dpr;
  canvas.height = (rect.height || 48) * dpr;

  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  drawIdleWaveform();
}

function drawIdleWaveform() {
  const canvas = dom.waveformCanvas;
  const ctx = canvas.getContext("2d");
  const width = canvas.width / (window.devicePixelRatio || 1);
  const height = canvas.height / (window.devicePixelRatio || 1);

  ctx.clearRect(0, 0, width, height);
  const barCount = 38;
  const barWidth = 3;
  const gap = (width - (barCount * barWidth)) / (barCount - 1);

  for (let i = 0; i < barCount; i++) {
    const x = i * (barWidth + gap);
    const barHeight = 4;
    const y = (height - barHeight) / 2;

    ctx.fillStyle = "#1e293b";
    ctx.beginPath();
    ctx.roundRect(x, y, barWidth, barHeight, 2);
    ctx.fill();
  }
}

function startVisualizer() {
  stopVisualizer();

  const canvas = dom.waveformCanvas;
  const ctx = canvas.getContext("2d");
  const width = canvas.width / (window.devicePixelRatio || 1);
  const height = canvas.height / (window.devicePixelRatio || 1);

  const barCount = 38;
  const barWidth = 3;
  const gap = (width - (barCount * barWidth)) / (barCount - 1);

  let phase = 0;

  function renderFrame() {
    ctx.clearRect(0, 0, width, height);
    phase += 0.08;

    for (let i = 0; i < barCount; i++) {
      const x = i * (barWidth + gap);
      
      // Multi-sine wave simulation with noise for realistic audio response
      const wave1 = Math.sin(phase + i * 0.28);
      const wave2 = Math.cos(phase * 1.4 + i * 0.15);
      const intensity = Math.abs(wave1 * 0.6 + wave2 * 0.4);
      
      const barHeight = Math.max(4, intensity * (height - 8));
      const y = (height - barHeight) / 2;

      // Studio Amber to Cyan gradient
      const grad = ctx.createLinearGradient(0, y, 0, y + barHeight);
      grad.addColorStop(0, "#fbbf24");
      grad.addColorStop(1, "#f59e0b");

      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.roundRect(x, y, barWidth, barHeight, 2);
      ctx.fill();
    }

    state.visualizerAnimId = requestAnimationFrame(renderFrame);
  }

  renderFrame();
}

function stopVisualizer() {
  if (state.visualizerAnimId) {
    cancelAnimationFrame(state.visualizerAnimId);
    state.visualizerAnimId = null;
  }
  drawIdleWaveform();
}

// ============================================================================
// SETTINGS & API KEY MANAGEMENT
// ============================================================================

function initApiStatus() {
  const key = state.apiKey.trim();
  if (key) {
    dom.apiStatusDot.className = "w-2 h-2 rounded-full bg-emerald-500 shadow-sm shadow-emerald-500/50";
    dom.apiStatusText.textContent = "API Key Active";
    dom.settingsApiKeyInput.value = key;
  } else {
    dom.apiStatusDot.className = "w-2 h-2 rounded-full bg-amber-500 animate-pulse";
    dom.apiStatusText.textContent = "Setup API Key";
  }
}

function openSettings() {
  dom.settingsApiKeyInput.value = state.apiKey;
  dom.testKeyFeedback.classList.add("hidden");
  dom.settingsModal.classList.remove("hidden");
  dom.settingsApiKeyInput.focus();
}

function closeSettings() {
  dom.settingsModal.classList.add("hidden");
}

function toggleKeyVisibility() {
  const isPass = dom.settingsApiKeyInput.type === "password";
  dom.settingsApiKeyInput.type = isPass ? "text" : "password";
  dom.eyeOpenIcon.classList.toggle("hidden", isPass);
  dom.eyeClosedIcon.classList.toggle("hidden", !isPass);
}

async function testApiKeyConnection() {
  const key = dom.settingsApiKeyInput.value.trim();
  if (!key) {
    showTestFeedback("Please enter an API key first.", false);
    return;
  }

  dom.testApiKeyBtn.textContent = "Testing...";
  dom.testApiKeyBtn.disabled = true;

  try {
    const resp = await fetch("/api/unrealspeech/test-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: key })
    });
    const result = await resp.json();
    if (result.valid) {
      showTestFeedback("✓ " + result.message, true);
    } else {
      showTestFeedback("✕ " + result.message, false);
    }
  } catch (err) {
    showTestFeedback("✕ Connection error: " + err.message, false);
  } finally {
    dom.testApiKeyBtn.textContent = "Test Connection";
    dom.testApiKeyBtn.disabled = false;
  }
}

function showTestFeedback(msg, isSuccess) {
  dom.testKeyFeedback.textContent = msg;
  dom.testKeyFeedback.className = isSuccess
    ? "p-2.5 rounded-xl text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
    : "p-2.5 rounded-xl text-xs font-medium bg-red-500/10 text-red-400 border border-red-500/20";
  dom.testKeyFeedback.classList.remove("hidden");
}

function saveSettings() {
  const key = dom.settingsApiKeyInput.value.trim();
  state.apiKey = key;
  if (key) {
    localStorage.setItem("unrealspeech_api_key", key);
    showToast("API Key saved to browser storage", "success");
  } else {
    localStorage.removeItem("unrealspeech_api_key");
    showToast("API Key removed", "info");
  }
  initApiStatus();
  closeSettings();
}

function clearApiKey() {
  dom.settingsApiKeyInput.value = "";
  state.apiKey = "";
  localStorage.removeItem("unrealspeech_api_key");
  initApiStatus();
  showTestFeedback("Key cleared from local storage.", false);
}

// ============================================================================
// HISTORY / TAKES DRAWER
// ============================================================================

function toggleHistoryDrawer() {
  dom.historyDrawer.classList.toggle("translate-x-full");
}

function closeHistoryDrawer() {
  dom.historyDrawer.classList.add("translate-x-full");
}

async function loadHistory() {
  try {
    let serverTakes = [];
    try {
      const resp = await fetch("/api/history");
      if (resp.ok) {
        const data = await resp.json();
        serverTakes = data.takes || [];
      }
    } catch (e) {
      console.warn("Could not fetch server history (expected on serverless cold starts):", e);
    }

    const clientTakes = getClientTakes();

    // Merge server takes and client takes (deduplicating by id)
    const takeMap = new Map();
    // Add client takes first (contains base64 audio_data for offline/serverless replay)
    clientTakes.forEach(t => takeMap.set(t.id, t));
    // Add or merge server takes
    serverTakes.forEach(t => {
      if (takeMap.has(t.id)) {
        takeMap.set(t.id, { ...t, audio_data: takeMap.get(t.id).audio_data || t.audio_data });
      } else {
        takeMap.set(t.id, t);
      }
    });

    const takes = Array.from(takeMap.values());
    takes.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));

    dom.historyCountBadge.textContent = takes.length;
    dom.historyTotalCount.textContent = `${takes.length} take${takes.length === 1 ? "" : "s"} saved`;

    if (takes.length === 0) {
      dom.historyList.innerHTML = `<div class="text-center py-12 text-slate-500 text-xs">No voiceover takes recorded yet.</div>`;
      return;
    }

    // Auto-select latest take on boot if none active
    if (!state.activeTakeUrl && takes.length > 0) {
      const latest = takes[0];
      setActiveTake(latest.audio_data || latest.audio_url, latest.filename, latest);
    }

    let html = "";
    takes.forEach(take => {
      const downloadHref = take.audio_data || `/api/download/${encodeURIComponent(take.filename)}`;
      html += `
        <div class="p-3.5 rounded-xl bg-studio-950 border border-studio-800 flex flex-col gap-2 transition-all hover:border-studio-700">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-amber-400">${escapeHtml(take.voice_id)} <span class="text-[10px] text-slate-500 font-mono">(${escapeHtml(take.bitrate)})</span></span>
            <span class="text-[10px] text-slate-500 font-mono">${escapeHtml(take.created_at_formatted || "")}</span>
          </div>
          <p class="text-xs text-slate-300 line-clamp-2 leading-relaxed">"${escapeHtml(take.text)}"</p>
          <div class="flex items-center justify-between pt-1 border-t border-studio-800/80 text-[11px]">
            <div class="flex items-center gap-3">
              <button class="play-take-btn text-amber-400 hover:text-amber-300 font-medium flex items-center gap-1 transition-colors" data-take-id="${take.id}" data-audio-url="${take.audio_url || ''}" data-filename="${escapeHtml(take.filename)}">
                <svg class="w-3 h-3 fill-current" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                Play
              </button>
              <a href="${downloadHref}" download="${escapeHtml(take.filename)}" class="download-take-btn text-slate-400 hover:text-amber-400 font-medium flex items-center gap-1 transition-colors" title="Download MP3 file directly">
                <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                Download MP3
              </a>
            </div>
            <button class="delete-take-btn text-slate-500 hover:text-red-400 transition-colors" data-take-id="${take.id}" title="Delete Take">
              <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/></svg>
            </button>
          </div>
        </div>
      `;
    });

    dom.historyList.innerHTML = html;

    // Attach listeners
    dom.historyList.querySelectorAll(".play-take-btn").forEach(b => {
      b.addEventListener("click", () => {
        const id = b.getAttribute("data-take-id");
        const take = takes.find(t => t.id === id);
        const url = (take && take.audio_data) || b.getAttribute("data-audio-url");
        const filename = b.getAttribute("data-filename");
        setActiveTake(url, filename, take);
        dom.remoteAudioPlayer.play();
        setPlayingUI(true);
        startVisualizer();
        closeHistoryDrawer();
      });
    });

    dom.historyList.querySelectorAll(".download-take-btn").forEach(btn => {
      btn.addEventListener("click", (e) => {
        const filename = btn.getAttribute("download") || "voiceover.mp3";
        showToast(`Downloading ${filename}...`, "info");
      });
    });

    dom.historyList.querySelectorAll(".delete-take-btn").forEach(b => {
      b.addEventListener("click", async () => {
        const id = b.getAttribute("data-take-id");
        if (confirm("Delete this take?")) {
          deleteClientTake(id);
          try {
            await fetch(`/api/history/${id}`, { method: "DELETE" });
          } catch (e) {}
          loadHistory();
        }
      });
    });

  } catch (err) {
    console.error("Failed to load history:", err);
  }
}

// ============================================================================
// GLOBAL SHORTCUTS & NOTIFICATIONS
// ============================================================================

function handleGlobalKeydown(e) {
  // If in teleprompter view and user begins typing, switch immediately back to Script Editor and focus textarea
  if (dom.teleprompterContainer && !dom.teleprompterContainer.classList.contains("hidden") && e.target !== dom.settingsApiKeyInput) {
    if (e.key === "Backspace" || e.key === "Enter" || (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey && e.code !== "Space")) {
      switchScriptView("edit");
      dom.scriptInput.focus();
    }
  }

  // Ctrl + Enter: Generate or Speak
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    if (state.engine === "neural") {
      generateNeuralAudio();
    } else {
      handleTogglePlay();
    }
    return;
  }

  // Space to toggle play/pause if not typing in text input
  if (e.code === "Space" && e.target !== dom.scriptInput && e.target !== dom.settingsApiKeyInput) {
    e.preventDefault();
    handleTogglePlay();
    return;
  }

  // Esc to Stop
  if (e.key === "Escape") {
    handleStopPlayback();
    closeSettings();
    closeHistoryDrawer();
  }
}

function showToast(message, type = "info") {
  const toast = document.createElement("div");
  const icons = {
    success: `<svg class="w-4 h-4 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>`,
    error: `<svg class="w-4 h-4 text-red-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
    warning: `<svg class="w-4 h-4 text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
    info: `<svg class="w-4 h-4 text-cyan-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`
  };

  toast.className = "flex items-center gap-2 px-4 py-3 rounded-xl bg-studio-900 border border-studio-700/80 text-xs font-semibold text-white shadow-2xl transition-all duration-300 transform translate-y-2 opacity-0 pointer-events-auto";
  toast.innerHTML = `${icons[type] || icons.info}<span>${escapeHtml(message)}</span>`;

  dom.toastContainer.appendChild(toast);

  // Animate in
  requestAnimationFrame(() => {
    toast.classList.remove("translate-y-2", "opacity-0");
  });

  // Remove after 3.5s
  setTimeout(() => {
    toast.classList.add("translate-y-2", "opacity-0");
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/[&<>"']/g, (m) => {
    return {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }[m];
  });
}
