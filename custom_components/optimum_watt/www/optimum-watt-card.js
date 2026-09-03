/**
 * Optimum Watt Lovelace card.
 *
 * Plain Web Component, no build step, no external dependencies. Talks to
 * the integration's websocket API (optimum_watt/*) to list, add,
 * edit, reorder and delete devices, and receives live state pushes via a
 * subscription — the card itself carries no device configuration.
 */

const STATUS_LABELS = {
  manual_on: "Manuell an",
  manual_off: "Manuell aus",
  auto_on: "An (Automatik)",
  auto_off: "Aus (Automatik)",
  disabled: "Regelung aus",
  catchup: "Pflichtlauf (Mindestlaufzeit)",
};

// What a device's threshold is measured against - keep in sync with
// THRESHOLD_BASIS_* in const.py. `needs` names the state flag that must be
// true (has_pv_production_entity / has_storage_entity) for the option to be
// usable; null means it's always available.
const THRESHOLD_BASIS_OPTIONS = [
  {
    value: "surplus",
    label: "Überschuss (Netzeinspeisung)",
    hint: "Schaltet ein, sobald genug Leistung ins Netz eingespeist wird.",
    needs: null,
  },
  {
    value: "production",
    label: "PV-Produktion",
    hint: "Schaltet ein, sobald die Anlage genug produziert – unabhängig vom Hausverbrauch.",
    needs: "has_pv_production_entity",
  },
  {
    value: "surplus_pre_storage",
    label: "Überschuss vor Speicherladung",
    hint: "Schaltet ein, sobald mehr produziert als verbraucht wird – noch bevor der Speicher lädt.",
    needs: "has_storage_entity",
  },
];

function fmtMinutes(seconds) {
  if (seconds === null || seconds === undefined) return "–";
  return Math.round(seconds / 60).toString();
}

function fmtPower(watts) {
  if (watts === null || watts === undefined || Number.isNaN(watts)) return "–";
  if (Math.abs(watts) >= 1000) return `${(watts / 1000).toFixed(2)} kW`;
  return `${Math.round(watts)} W`;
}

function fmtSeconds(sec) {
  if (sec === null || sec === undefined) return null;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return m > 0 ? `${m}:${String(s).padStart(2, "0")} min` : `${s} s`;
}

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

class OptimumWattCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._built = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) {
      this._buildStaticShell();
      this._built = true;
    }
    if (!this._subscribed) {
      this._subscribe();
    } else if (this._root) {
      this._root.querySelectorAll("ha-entity-picker").forEach((p) => {
        p.hass = hass;
      });
    }
  }

  getCardSize() {
    const deviceCount = this._latestState?.devices?.length ?? 2;
    return 3 + deviceCount + (this._formOpen() ? 2 : 0);
  }

  connectedCallback() {
    if (this._built && this._hass && !this._subscribed) this._subscribe();
  }

  disconnectedCallback() {
    if (this._unsubscribe) {
      this._unsubscribe();
      this._unsubscribe = null;
    }
    this._subscribed = false;
  }

  _formOpen() {
    return (
      (this._editingId !== null && this._editingId !== undefined) ||
      this._addingNew ||
      this._editingPriorityId !== null && this._editingPriorityId !== undefined
    );
  }

  async _ensureEntryId() {
    if (this._entryId) return;
    if (this._config.entry_id) {
      this._entryId = this._config.entry_id;
      return;
    }
    try {
      const entries = await this._hass.callWS({ type: "config_entries/get" });
      const match = entries.find((e) => e.domain === "optimum_watt");
      if (match) this._entryId = match.entry_id;
    } catch (err) {
      // ignore, handled by the "not configured" empty state below
    }
  }

  async _subscribe() {
    if (!this._hass || this._subscribed) return;
    await this._ensureEntryId();
    if (!this._entryId) {
      this._renderError("Keine Optimum-Watt-Instanz gefunden.");
      return;
    }
    this._subscribed = true;
    this._unsubscribe = await this._hass.connection.subscribeMessage(
      (state) => {
        this._latestState = state;
        this._render();
      },
      { type: "optimum_watt/subscribe", entry_id: this._entryId }
    );
  }

  async _callWS(payload) {
    return this._hass.connection.sendMessagePromise({ entry_id: this._entryId, ...payload });
  }

  _renderError(message) {
    if (!this._els) return;
    this._els.devices.innerHTML = `<div class="em-empty">${escapeHtml(message)}</div>`;
  }

  // -- Actions -----------------------------------------------------------

  _toggleAuto() {
    if (!this._latestState) return;
    const enabled = !this._latestState.auto_mode;
    // Optimistic: reflect the click instantly, the next push confirms it.
    this._latestState.auto_mode = enabled;
    this._render();
    this._callWS({ type: "optimum_watt/set_auto_mode", enabled });
  }

  _setMode(deviceId, mode) {
    const device = this._latestState?.devices.find((d) => d.id === deviceId);
    if (device) {
      // Optimistic: flip the button state instantly instead of waiting for
      // the round trip (which may include an actual switch call to real
      // hardware and would otherwise make the button feel unresponsive).
      device.mode = mode;
      device.remaining_seconds = null;
      if (mode === "disabled") device.status = "disabled";
      else if (mode === "on") device.status = "manual_on";
      else if (mode === "off") device.status = "manual_off";
      else device.status = device.active ? "auto_on" : "auto_off";
      this._render();
    }
    this._callWS({ type: "optimum_watt/update_device", device_id: deviceId, mode });
  }

  _moveDevice(deviceId, direction) {
    const ids = this._latestState.devices.map((d) => d.id);
    const idx = ids.indexOf(deviceId);
    const swapIdx = idx + direction;
    if (swapIdx < 0 || swapIdx >= ids.length) return;
    [ids[idx], ids[swapIdx]] = [ids[swapIdx], ids[idx]];
    this._callWS({ type: "optimum_watt/reorder_devices", device_ids: ids });
  }

  _setDevicePosition(deviceId, newPosition) {
    const ids = this._latestState.devices.map((d) => d.id);
    const idx = ids.indexOf(deviceId);
    if (idx === -1) return;
    const target = Math.max(0, Math.min(ids.length - 1, Math.round(newPosition) - 1));
    if (target === idx) return;
    ids.splice(idx, 1);
    ids.splice(target, 0, deviceId);
    this._callWS({ type: "optimum_watt/reorder_devices", device_ids: ids });
  }

  _startEditPriority(deviceId) {
    if (this._addingNew || (this._editingId !== null && this._editingId !== undefined)) return;
    this._editingPriorityId = deviceId;
    this._renderDevicesWithForm();
  }

  _commitPriority(deviceId, rawValue) {
    this._editingPriorityId = null;
    const value = Number(rawValue);
    if (Number.isFinite(value) && value > 0) {
      this._setDevicePosition(deviceId, value);
    }
    this._render();
  }

  _deleteDevice(deviceId, name) {
    if (!window.confirm(`Gerät "${name}" wirklich löschen?`)) return;
    this._callWS({ type: "optimum_watt/remove_device", device_id: deviceId });
  }

  _openAdd() {
    this._addingNew = true;
    this._editingId = null;
    this._draft = {
      name: "",
      entity_id: "",
      power_w: "500",
      on_delay_min: "5",
      off_delay_min: "5",
      hysteresis_w: "0",
      threshold_basis: "surplus",
      min_soc_percent: "",
      min_runtime_minutes: "",
      min_runtime_deadline: "",
      min_on_duration_min: "",
    };
    this._renderDevicesWithForm();
  }

  _openEdit(device) {
    this._editingId = device.id;
    this._addingNew = false;
    this._draft = {
      name: device.name,
      entity_id: device.entity_id,
      power_w: String(device.power_w),
      on_delay_min: String(device.on_delay_s / 60),
      off_delay_min: String(device.off_delay_s / 60),
      hysteresis_w: String(device.hysteresis_w),
      threshold_basis: device.threshold_basis || "surplus",
      min_soc_percent: device.min_soc_percent ? String(device.min_soc_percent) : "",
      min_runtime_minutes: device.min_runtime_s ? String(device.min_runtime_s / 60) : "",
      min_runtime_deadline: device.min_runtime_deadline || "",
      min_on_duration_min: device.min_on_duration_s ? String(device.min_on_duration_s / 60) : "",
    };
    this._renderDevicesWithForm();
  }

  _cancelForm() {
    this._addingNew = false;
    this._editingId = null;
    this._draft = null;
    this._render();
  }

  _draftPayload() {
    const d = this._draft;
    const minutes = Number(d.min_runtime_minutes);
    const useMinRuntime = d.min_runtime_minutes !== "" && minutes > 0 && d.min_runtime_deadline;
    return {
      name: d.name.trim(),
      entity_id: d.entity_id.trim(),
      power_w: Number(d.power_w),
      hysteresis_w: d.hysteresis_w === "" ? undefined : Number(d.hysteresis_w),
      threshold_basis: d.threshold_basis || "surplus",
      min_soc_percent:
        d.min_soc_percent !== "" && Number(d.min_soc_percent) > 0 ? Number(d.min_soc_percent) : 0,
      on_delay_s: Math.round(Number(d.on_delay_min) * 60),
      off_delay_s: Math.round(Number(d.off_delay_min) * 60),
      min_runtime_s: useMinRuntime ? Math.round(minutes * 60) : 0,
      min_runtime_deadline: useMinRuntime ? d.min_runtime_deadline : "",
      min_on_duration_s:
        d.min_on_duration_min !== "" && Number(d.min_on_duration_min) > 0
          ? Math.round(Number(d.min_on_duration_min) * 60)
          : 0,
    };
  }

  _saveForm() {
    const d = this._draft;
    const hasMinutes = d.min_runtime_minutes !== "" && Number(d.min_runtime_minutes) > 0;
    const hasDeadline = !!d.min_runtime_deadline;
    if (hasMinutes !== hasDeadline) {
      window.alert("Für die Mindestlaufzeit bitte sowohl Minuten als auch Uhrzeit angeben (oder beide leer lassen).");
      return;
    }
    const payload = this._draftPayload();
    if (!payload.name || !payload.entity_id || !Number.isFinite(payload.power_w)) {
      window.alert("Bitte Name, Schalter und Leistungsbedarf ausfüllen.");
      return;
    }
    if (this._addingNew) {
      this._callWS({ type: "optimum_watt/add_device", ...payload });
    } else {
      this._callWS({ type: "optimum_watt/update_device", device_id: this._editingId, ...payload });
    }
    this._cancelForm();
  }

  // -- Rendering -----------------------------------------------------------

  _buildStaticShell() {
    const style = document.createElement("style");
    style.textContent = `
      ha-card { padding: 16px; }
      .em-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
      .em-title { font-size: 1.1em; font-weight: 500; }
      .em-logo { display: flex; align-items: center; gap: 10px; }
      .em-logo-mark { width: 44px; height: 44px; flex-shrink: 0; }
      .em-logo-word { font-size: 1.3em; font-weight: 700; letter-spacing: -0.01em; color: var(--primary-text-color); }
      .em-header-right { display: flex; align-items: center; gap: 10px; }
      .em-active-count { color: var(--secondary-text-color); font-size: 0.9em; }
      .em-auto-toggle { cursor: pointer; }
      .em-surplus { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; }
      .em-surplus .value { font-size: 2em; font-weight: 600; }
      .em-surplus .label { color: var(--secondary-text-color); font-size: 0.9em; }
      .em-extra-readings { color: var(--secondary-text-color); font-size: 0.85em; margin: -4px 0 8px; }
      .em-alert { display: flex; align-items: flex-start; gap: 8px; background: var(--error-color, #d32f2f); color: white; padding: 10px 12px; border-radius: 8px; margin-bottom: 12px; font-size: 0.85em; font-weight: 500; }
      .em-alert[hidden] { display: none; }
      .em-alert ha-icon { --mdc-icon-size: 20px; flex-shrink: 0; }
      .em-legend { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 4px 10px; margin: 0 0 14px; }
      .em-legend-item { display: flex; align-items: center; gap: 4px; font-size: 0.72em; color: var(--secondary-text-color); white-space: nowrap; }
      .em-legend-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
      .em-legend-dot.on { background: var(--success-color, #43a047); }
      .em-legend-dot.pending { background: var(--warning-color, #fb8c00); }
      .em-legend-dot.catchup { background: var(--info-color, #3b6fd4); }
      .em-legend-dot.disabled { background: var(--disabled-text-color, #9e9e9e); }
      .em-device { border-radius: 10px; padding: 10px 12px; margin-bottom: 8px; background: var(--secondary-background-color, #f2f2f2); display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
      .em-device.on { background: var(--success-color, #43a047); color: white; }
      .em-device.pending { background: var(--warning-color, #fb8c00); color: white; }
      .em-device.catchup { background: var(--info-color, #3b6fd4); color: white; }
      .em-device.unreachable { background: var(--error-color, #db4437); color: white; }
      .em-device.disabled { opacity: 0.55; }
      .em-device ha-icon { --mdc-icon-size: 24px; flex-shrink: 0; }
      .em-device-order { display: flex; flex-direction: column; align-items: center; gap: 2px; }
      .em-device-num { font-size: 0.72em; font-weight: 600; opacity: 0.75; line-height: 1; cursor: pointer; padding: 2px 4px; border-radius: 4px; }
      .em-device-num:hover { background: rgba(127,127,127,0.2); }
      .em-device-num-input { width: 30px; font-size: 0.72em; font-weight: 600; text-align: center; padding: 1px 0; border-radius: 4px; border: 1px solid var(--divider-color, #ccc); background: var(--card-background-color); color: var(--primary-text-color); }
      .em-device-main { flex: 1 1 140px; min-width: 140px; }
      .em-device-name { font-weight: 500; overflow-wrap: break-word; word-break: break-word; }
      .em-device-sub { font-size: 0.82em; opacity: 0.85; overflow-wrap: break-word; word-break: break-word; }
      .em-modes { display: flex; flex-wrap: wrap; gap: 4px; flex-shrink: 0; margin-left: auto; }
      .em-modes button { border: none; border-radius: 6px; padding: 4px 7px; font-size: 0.72em; cursor: pointer; background: rgba(0,0,0,0.12); color: inherit; white-space: nowrap; }
      .em-modes button.active { background: rgba(255,255,255,0.9); color: #222; font-weight: 600; }
      .em-icon-btn { border: none; background: rgba(0,0,0,0.1); color: inherit; border-radius: 6px; width: 28px; height: 28px; font-size: 0.85em; cursor: pointer; flex-shrink: 0; }
      .em-icon-btn:disabled { opacity: 0.3; cursor: default; }
      .em-add-btn { width: 100%; margin-top: 6px; padding: 10px; border-radius: 10px; border: 1px dashed var(--divider-color, #ccc); background: transparent; color: var(--primary-color); font-weight: 500; cursor: pointer; }
      .em-empty { color: var(--secondary-text-color); text-align: center; padding: 16px 0; }
      .em-form { border-radius: 10px; padding: 12px; margin-bottom: 8px; background: var(--card-background-color); border: 1px solid var(--divider-color, #ddd); }
      .em-form-row { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; min-width: 0; }
      .em-form-row.two { flex-direction: row; gap: 10px; flex-wrap: wrap; }
      .em-form-row.two > div { flex: 1 1 140px; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
      .em-form-row label { font-size: 0.8em; color: var(--secondary-text-color); overflow-wrap: break-word; }
      .em-form-row input, .em-form-row select { border-radius: 6px; border: 1px solid var(--divider-color, #ccc); padding: 6px 8px; background: var(--card-background-color); color: var(--primary-text-color); width: 100%; box-sizing: border-box; min-width: 0; }
      .em-form { min-width: 0; }
      #em-f-entity-wrap, #em-f-entity-wrap ha-entity-picker { width: 100%; box-sizing: border-box; }
      .em-form-advanced { margin-bottom: 10px; }
      .em-form-advanced summary { cursor: pointer; font-size: 0.85em; color: var(--secondary-text-color); }
      .em-form-hint { font-size: 0.78em; color: var(--secondary-text-color); margin: -4px 0 4px; }
      .em-form-actions { display: flex; gap: 8px; justify-content: flex-end; }
      .em-btn-primary { background: var(--primary-color); color: var(--text-primary-color, white); border: none; border-radius: 6px; padding: 8px 14px; cursor: pointer; font-weight: 500; }
      .em-btn-secondary { background: transparent; color: var(--secondary-text-color); border: none; border-radius: 6px; padding: 8px 14px; cursor: pointer; }
      .em-settings { margin-top: 14px; border-top: 1px solid var(--divider-color, #ddd); padding-top: 10px; }
      .em-settings summary { cursor: pointer; font-weight: 500; color: var(--primary-text-color); }
      .em-settings-feedback { font-size: 0.82em; align-self: center; margin-right: auto; }
      .em-settings-version { font-size: 0.76em; color: var(--secondary-text-color); margin: 12px 0 0; text-align: right; }
    `;

    const titleHtml = this._config.title
      ? `<div class="em-title">${escapeHtml(this._config.title)}</div>`
      : `
        <div class="em-logo" aria-label="Optimum Watt">
          <svg class="em-logo-mark" viewBox="0 0 100 100" role="img" aria-hidden="true">
            <defs>
              <linearGradient id="em-logo-wave" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stop-color="#3B82C4"/>
                <stop offset="100%" stop-color="#3FAE72"/>
              </linearGradient>
            </defs>
            <rect width="100" height="100" rx="20" fill="#1C2126"/>
            <circle cx="26" cy="54" r="11.9" fill="none" stroke="url(#em-logo-wave)" stroke-width="5.5" stroke-linecap="round"/>
            <g transform="translate(34.3,20.9) scale(0.6)">
              <path d="M13.50 29.00 L25.50 75.00 L37.00 44.00 L48.50 75.00 L58.50 29.00 L58.78 28.28 L59.05 27.57 L59.33 26.88 L59.61 26.21 L59.89 25.58 L60.16 24.99 L60.44 24.45 L60.72 23.95 L61.00 23.50 L61.27 23.11 L61.55 22.78 L61.83 22.51 L62.10 22.30 L62.38 22.16 L62.66 22.09 L62.94 22.08 L63.21 22.14 L63.49 22.26 L63.77 22.45 L64.05 22.69 L64.32 22.99 L64.60 23.34 L64.88 23.75 L65.15 24.19 L65.43 24.68 L65.71 25.21 L65.99 25.76 L66.26 26.34 L66.54 26.94 L66.82 27.55 L67.10 28.17 L67.37 28.78 L67.65 29.40 L67.93 30.00 L68.20 30.58 L68.48 31.15 L68.76 31.68 L69.04 32.19 L69.31 32.66 L69.59 33.09 L69.87 33.47 L70.15 33.81 L70.42 34.10 L70.70 34.34 L70.98 34.52 L71.25 34.65 L71.53 34.73 L71.81 34.75 L72.09 34.71 L72.36 34.62 L72.64 34.48 L72.92 34.29 L73.20 34.06 L73.47 33.77 L73.75 33.45 L74.03 33.09 L74.30 32.69 L74.58 32.27 L74.86 31.82 L75.14 31.35 L75.41 30.86 L75.69 30.36 L75.97 29.86 L76.25 29.35 L76.52 28.85 L76.80 28.36 L77.08 27.88 L77.35 27.42 L77.63 26.98 L77.91 26.56 L78.19 26.18 L78.46 25.82 L78.74 25.51 L79.02 25.23 L79.30 24.98 L79.57 24.79 L79.85 24.63 L80.13 24.52 L80.40 24.45 L80.68 24.43 L80.96 24.45 L81.24 24.51 L81.51 24.61 L81.79 24.76 L82.07 24.94 L82.35 25.16 L82.62 25.41 L82.90 25.69 L83.18 25.99 L83.45 26.32 L83.73 26.67 L84.01 27.04 L84.29 27.42 L84.56 27.81 L84.84 28.20 L85.12 28.59 L85.40 28.98 L85.67 29.36 L85.95 29.73 L86.23 30.09 L86.50 30.43 L86.78 30.75 L87.06 31.05 L87.34 31.32 L87.61 31.57 L87.89 31.78 L88.17 31.97 L88.45 32.12 L88.72 32.24 L89.00 32.33" fill="none" stroke="url(#em-logo-wave)" stroke-width="9.17" stroke-linecap="round" stroke-linejoin="round"/>
            </g>
          </svg>
          <span class="em-logo-word">Optimum Watt</span>
        </div>
      `;

    const card = document.createElement("ha-card");
    card.innerHTML = `
      <div class="em-header">
        ${titleHtml}
        <div class="em-header-right">
          <span class="em-active-count" id="em-active-count"></span>
          <ha-icon class="em-auto-toggle" id="em-auto-icon"></ha-icon>
        </div>
      </div>
      <div class="em-surplus">
        <div class="value" id="em-surplus-value">–</div>
        <div class="label">Überschuss aktuell</div>
      </div>
      <div class="em-extra-readings" id="em-extra-readings" hidden></div>
      <div class="em-alert" id="em-alert" hidden>
        <ha-icon icon="mdi:alert"></ha-icon>
        <span id="em-alert-text"></span>
      </div>
      <div class="em-legend">
        <span class="em-legend-item"><span class="em-legend-dot on"></span>An</span>
        <span class="em-legend-item"><span class="em-legend-dot pending"></span>Wartet</span>
        <span class="em-legend-item"><span class="em-legend-dot catchup"></span>Pflichtlauf</span>
        <span class="em-legend-item"><span class="em-legend-dot disabled"></span>Regelung aus</span>
      </div>
      <div id="em-devices"></div>
      <button class="em-add-btn" id="em-add-btn">+ Gerät hinzufügen</button>
      <details class="em-settings" id="em-settings">
        <summary>Einstellungen</summary>
        <div class="em-form-row" style="margin-top: 8px;">
          <label>Sensor-Timeout (min)</label>
          <input type="number" id="em-settings-timeout" min="0" step="1" placeholder="leer = aus" />
        </div>
        <p class="em-form-hint">
          Kommt vom Einspeise-Sensor so lange kein neuer Wert, werden alle aktiven
          Schalter (außer „Regelung aus") sicherheitshalber nacheinander im
          10-Sekunden-Takt abgeschaltet.
        </p>
        <div class="em-form-actions">
          <span class="em-settings-feedback" id="em-settings-feedback"></span>
          <button class="em-btn-primary" id="em-settings-save">Speichern</button>
        </div>
        <p class="em-settings-version" id="em-settings-version"></p>
      </details>
    `;

    this._root = document.createElement("div");
    this._root.appendChild(style);
    this._root.appendChild(card);

    this.innerHTML = "";
    this.appendChild(this._root);

    this._els = {
      autoIcon: card.querySelector("#em-auto-icon"),
      surplusValue: card.querySelector("#em-surplus-value"),
      extraReadings: card.querySelector("#em-extra-readings"),
      activeCount: card.querySelector("#em-active-count"),
      devices: card.querySelector("#em-devices"),
      addBtn: card.querySelector("#em-add-btn"),
      alert: card.querySelector("#em-alert"),
      alertText: card.querySelector("#em-alert-text"),
      settingsTimeout: card.querySelector("#em-settings-timeout"),
      settingsSave: card.querySelector("#em-settings-save"),
      settingsFeedback: card.querySelector("#em-settings-feedback"),
      settingsVersion: card.querySelector("#em-settings-version"),
    };

    this._els.autoIcon.addEventListener("click", () => this._toggleAuto());
    this._els.addBtn.addEventListener("click", () => this._openAdd());
    this._els.settingsSave.addEventListener("click", () => this._saveSettings());
  }

  _showSettingsFeedback(text, isError) {
    const el = this._els.settingsFeedback;
    el.textContent = text;
    el.style.color = isError ? "var(--error-color, #d32f2f)" : "var(--success-color, #43a047)";
    clearTimeout(this._settingsFeedbackTimeout);
    this._settingsFeedbackTimeout = setTimeout(() => {
      el.textContent = "";
    }, 3000);
  }

  async _saveSettings() {
    const raw = this._els.settingsTimeout.value;
    const minutes = Number(raw);
    const sensor_timeout_s = raw !== "" && minutes > 0 ? Math.round(minutes * 60) : 0;
    this._els.settingsSave.disabled = true;
    try {
      await this._callWS({ type: "optimum_watt/set_settings", sensor_timeout_s });
      this._showSettingsFeedback("Gespeichert ✓", false);
    } catch (err) {
      this._showSettingsFeedback("Fehler beim Speichern", true);
    } finally {
      this._els.settingsSave.disabled = false;
    }
  }

  _render() {
    const state = this._latestState;
    if (!state) return;

    this._els.surplusValue.textContent = fmtPower(state.surplus_w);
    const extraParts = [];
    if (state.has_pv_production_entity) extraParts.push(`Produktion ${fmtPower(state.production_w)}`);
    if (state.has_storage_entity) extraParts.push(`Speicher ${fmtPower(state.storage_w)}`);
    if (state.has_storage_soc_entity) {
      const soc = state.storage_soc;
      extraParts.push(`SoC ${soc === null || soc === undefined ? "–" : Math.round(soc) + "%"}`);
    }
    this._els.extraReadings.hidden = extraParts.length === 0;
    this._els.extraReadings.textContent = extraParts.join(" · ");
    this._els.activeCount.textContent = `${state.regulated_count} / ${state.devices.length} geregelt`;
    this._els.autoIcon.setAttribute(
      "icon",
      state.auto_mode ? "mdi:toggle-switch" : "mdi:toggle-switch-off-outline"
    );
    this._els.autoIcon.style.color = state.auto_mode
      ? "var(--success-color, #43a047)"
      : "var(--disabled-text-color, #9e9e9e)";

    this._els.alert.hidden = !state.sensor_stale;
    this._els.alertText.textContent = state.sensor_stale
      ? `Kein neuer Wert vom Einspeise-Sensor seit über ${fmtMinutes(state.sensor_timeout_s)} min – ` +
        "aktive Geräte werden sicherheitshalber nacheinander abgeschaltet."
      : "";

    // Don't stomp on the field while the user is actively editing it.
    if (document.activeElement !== this._els.settingsTimeout) {
      this._els.settingsTimeout.value = state.sensor_timeout_s
        ? String(state.sensor_timeout_s / 60)
        : "";
    }

    this._els.settingsVersion.textContent = state.version
      ? `Optimum Watt v${state.version}`
      : "";

    // Skip rebuilding the device list while a form is open, so a live push
    // (every few seconds) doesn't rip focus out of an input the user is
    // still typing in. The form itself always reflects the latest draft.
    if (this._formOpen()) return;

    this._els.devices.innerHTML = "";

    state.devices.forEach((device, idx) => {
      this._els.devices.appendChild(this._renderDeviceRow(device, idx, state.devices.length));
    });

    if (state.devices.length === 0) {
      const empty = document.createElement("div");
      empty.className = "em-empty";
      empty.textContent = "Noch keine Geräte angelegt.";
      this._els.devices.appendChild(empty);
    }
  }

  _renderDevicesWithForm() {
    // Called right after opening the add/edit form, so it appears immediately
    // instead of waiting for the next live push.
    const state = this._latestState;
    if (!state) return;
    this._els.devices.innerHTML = "";
    state.devices.forEach((device, idx) => {
      if (this._editingId === device.id) {
        this._els.devices.appendChild(this._renderForm());
        return;
      }
      this._els.devices.appendChild(this._renderDeviceRow(device, idx, state.devices.length));
    });
    if (this._addingNew) {
      this._els.devices.appendChild(this._renderForm());
    }
  }

  _renderDeviceRow(device, idx, total) {
    const el = document.createElement("div");
    el.className = "em-device";
    const pending = device.remaining_seconds !== null && device.remaining_seconds !== undefined;
    if (device.mode === "disabled") el.classList.add("disabled");
    else if (device.switch_unreachable) el.classList.add("unreachable");
    else if (device.catchup_active) el.classList.add("catchup");
    else if (device.active) el.classList.add("on");
    else if (pending) el.classList.add("pending");

    let sub = `${STATUS_LABELS[device.status] || device.status} · ${fmtPower(device.power_w)}`;
    if (device.threshold_basis && device.threshold_basis !== "surplus") {
      const basisOpt = THRESHOLD_BASIS_OPTIONS.find((o) => o.value === device.threshold_basis);
      if (basisOpt) sub += ` · Basis: ${basisOpt.label}`;
    }
    if (device.min_soc_percent) {
      sub += ` · ab ${Math.round(device.min_soc_percent)}% Speicher`;
    }
    if (device.switch_unreachable) {
      sub += ` · ⚠ Schalter nicht erreichbar`;
    } else {
      const remainingText = fmtSeconds(device.remaining_seconds);
      if (remainingText) {
        sub += device.active ? ` · schaltet in ${remainingText} ab` : ` · schaltet in ${remainingText} ein`;
      }
    }
    if (device.min_runtime_s) {
      sub += ` · ${fmtMinutes(device.runtime_today_s)}/${fmtMinutes(device.min_runtime_s)} min bis ${device.min_runtime_deadline}`;
    }

    const editingPriority = this._editingPriorityId === device.id;
    const numHtml = editingPriority
      ? `<input type="number" class="em-device-num-input" min="1" max="${total}" step="1" value="${idx + 1}" />`
      : `<span class="em-device-num" title="Klicken, um Position direkt einzugeben">${idx + 1}</span>`;

    el.innerHTML = `
      <div class="em-device-order">
        <button class="em-icon-btn" data-action="up" ${idx === 0 ? "disabled" : ""} title="Höhere Priorität">▲</button>
        ${numHtml}
        <button class="em-icon-btn" data-action="down" ${idx === total - 1 ? "disabled" : ""} title="Niedrigere Priorität">▼</button>
      </div>
      <ha-icon icon="mdi:power-socket-eu"></ha-icon>
      <div class="em-device-main">
        <div class="em-device-name">${escapeHtml(device.name)}</div>
        <div class="em-device-sub">${escapeHtml(sub)}</div>
      </div>
      <div class="em-modes">
        <button data-mode="auto" class="${device.mode === "auto" ? "active" : ""}">Auto</button>
        <button data-mode="on" class="${device.mode === "on" ? "active" : ""}">An</button>
        <button data-mode="off" class="${device.mode === "off" ? "active" : ""}">Aus</button>
        <button data-mode="disabled" class="${device.mode === "disabled" ? "active" : ""}" title="Optimum Watt fasst diesen Schalter nicht an">Regelung aus</button>
      </div>
      <button class="em-icon-btn" data-action="edit" title="Bearbeiten">✎</button>
      <button class="em-icon-btn" data-action="delete" title="Löschen">🗑</button>
    `;

    el.querySelector('[data-action="up"]').addEventListener("click", () => this._moveDevice(device.id, -1));
    el.querySelector('[data-action="down"]').addEventListener("click", () => this._moveDevice(device.id, 1));
    el.querySelector('[data-action="edit"]').addEventListener("click", () => this._openEdit(device));
    el.querySelector('[data-action="delete"]').addEventListener("click", () => this._deleteDevice(device.id, device.name));
    el.querySelectorAll(".em-modes button").forEach((btn) => {
      btn.addEventListener("click", () => this._setMode(device.id, btn.getAttribute("data-mode")));
    });

    if (editingPriority) {
      const input = el.querySelector(".em-device-num-input");
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") input.blur();
      });
      input.addEventListener("blur", () => this._commitPriority(device.id, input.value));
      requestAnimationFrame(() => {
        input.focus();
        input.select();
      });
    } else {
      el.querySelector(".em-device-num").addEventListener("click", () => this._startEditPriority(device.id));
    }

    return el;
  }

  _renderForm() {
    const d = this._draft;
    const isAdd = this._addingNew;
    const wrap = document.createElement("div");
    wrap.className = "em-form";
    wrap.innerHTML = `
      <div class="em-form-row">
        <label>Name</label>
        <input type="text" id="em-f-name" value="${escapeHtml(d.name)}" placeholder="z. B. Boiler Stufe 1" />
      </div>
      <div class="em-form-row">
        <label>Schalter</label>
        <div id="em-f-entity-wrap"></div>
      </div>
      <div class="em-form-row">
        <label>Leistungsbedarf (W) – zugleich Einschaltschwelle</label>
        <input type="number" id="em-f-power" value="${escapeHtml(d.power_w)}" min="0" step="10" />
      </div>
      <div class="em-form-row">
        <label>Einschaltschwelle bezieht sich auf</label>
        <select id="em-f-basis"></select>
        <p class="em-form-hint" id="em-f-basis-hint"></p>
      </div>
      <div class="em-form-row">
        <label>Mindest-Speicher-Ladestand (%) für Einschaltung</label>
        <input type="number" id="em-f-min-soc" value="${escapeHtml(d.min_soc_percent)}" min="0" max="100" step="1" placeholder="leer = keine Einschränkung" />
        <p class="em-form-hint" id="em-f-min-soc-hint"></p>
      </div>
      <div class="em-form-row two">
        <div>
          <label>Einschaltverzögerung (min)</label>
          <input type="number" id="em-f-on-delay" value="${escapeHtml(d.on_delay_min)}" min="0" step="1" />
        </div>
        <div>
          <label>Ausschaltverzögerung (min)</label>
          <input type="number" id="em-f-off-delay" value="${escapeHtml(d.off_delay_min)}" min="0" step="1" />
        </div>
      </div>
      <details class="em-form-advanced">
        <summary>Erweitert</summary>
        <div class="em-form-row" style="margin-top: 8px;">
          <label>Hysterese (W) – Abstand zwischen Ein- und Ausschaltschwelle</label>
          <input type="number" id="em-f-hysteresis" value="${escapeHtml(d.hysteresis_w)}" min="0" step="10" />
        </div>
        <div class="em-form-row two">
          <div>
            <label>Mindestlaufzeit pro Tag (min)</label>
            <input type="number" id="em-f-min-runtime" value="${escapeHtml(d.min_runtime_minutes)}" min="0" step="5" placeholder="leer = aus" />
          </div>
          <div>
            <label>… bis Uhrzeit</label>
            <input type="time" id="em-f-min-runtime-deadline" value="${escapeHtml(d.min_runtime_deadline)}" />
          </div>
        </div>
        <p class="em-form-hint">Wird die Mindestlaufzeit sonst nicht erreicht, schaltet Optimum Watt notfalls auch ohne Überschuss ein, rechtzeitig vor der Uhrzeit.</p>
        <div class="em-form-row" style="margin-top: 8px;">
          <label>Mindestlaufzeit pro Aktivierung (min)</label>
          <input type="number" id="em-f-min-on-duration" value="${escapeHtml(d.min_on_duration_min)}" min="0" step="1" placeholder="leer = aus" />
        </div>
        <p class="em-form-hint">Einmal eingeschaltet, läuft das Gerät mindestens so lange weiter, auch wenn der Überschuss vorher wegfällt.</p>
      </details>
      <div class="em-form-actions">
        <button class="em-btn-secondary" id="em-f-cancel">Abbrechen</button>
        <button class="em-btn-primary" id="em-f-save">${isAdd ? "Hinzufügen" : "Speichern"}</button>
      </div>
    `;

    wrap.querySelector("#em-f-name").addEventListener("input", (e) => (this._draft.name = e.target.value));
    wrap.querySelector("#em-f-power").addEventListener("input", (e) => (this._draft.power_w = e.target.value));
    wrap.querySelector("#em-f-on-delay").addEventListener("input", (e) => (this._draft.on_delay_min = e.target.value));
    wrap.querySelector("#em-f-off-delay").addEventListener("input", (e) => (this._draft.off_delay_min = e.target.value));
    wrap.querySelector("#em-f-hysteresis").addEventListener("input", (e) => (this._draft.hysteresis_w = e.target.value));
    wrap.querySelector("#em-f-min-soc").addEventListener("input", (e) => (this._draft.min_soc_percent = e.target.value));
    this._renderBasisSelect(wrap);
    this._renderMinSocHint(wrap);
    wrap.querySelector("#em-f-min-runtime").addEventListener("input", (e) => (this._draft.min_runtime_minutes = e.target.value));
    wrap.querySelector("#em-f-min-on-duration").addEventListener("input", (e) => (this._draft.min_on_duration_min = e.target.value));
    wrap.querySelector("#em-f-min-runtime-deadline").addEventListener("input", (e) => (this._draft.min_runtime_deadline = e.target.value));
    wrap.querySelector("#em-f-save").addEventListener("click", () => this._saveForm());
    wrap.querySelector("#em-f-cancel").addEventListener("click", () => this._cancelForm());

    const entityWrap = wrap.querySelector("#em-f-entity-wrap");
    if (customElements.get("ha-entity-picker")) {
      const picker = document.createElement("ha-entity-picker");
      picker.hass = this._hass;
      picker.value = d.entity_id;
      picker.includeDomains = ["switch"];
      picker.allowCustomEntity = true;
      picker.addEventListener("value-changed", (e) => {
        this._draft.entity_id = e.detail.value || "";
      });
      entityWrap.appendChild(picker);
    } else {
      const input = document.createElement("input");
      input.type = "text";
      input.placeholder = "switch.beispiel";
      input.value = d.entity_id;
      input.setAttribute("list", "em-switch-entities");
      input.addEventListener("input", (e) => (this._draft.entity_id = e.target.value));
      entityWrap.appendChild(input);

      const datalist = document.createElement("datalist");
      datalist.id = "em-switch-entities";
      Object.keys(this._hass.states)
        .filter((eid) => eid.startsWith("switch."))
        .forEach((eid) => {
          const opt = document.createElement("option");
          opt.value = eid;
          datalist.appendChild(opt);
        });
      entityWrap.appendChild(datalist);
    }

    return wrap;
  }

  _renderBasisSelect(wrap) {
    const select = wrap.querySelector("#em-f-basis");
    const hint = wrap.querySelector("#em-f-basis-hint");
    const state = this._latestState || {};
    select.innerHTML = THRESHOLD_BASIS_OPTIONS.map(
      (opt) => `<option value="${opt.value}">${escapeHtml(opt.label)}</option>`
    ).join("");
    select.value = this._draft.threshold_basis;

    const updateHint = () => {
      const opt = THRESHOLD_BASIS_OPTIONS.find((o) => o.value === select.value) || THRESHOLD_BASIS_OPTIONS[0];
      const unavailable = opt.needs && !state[opt.needs];
      hint.textContent = unavailable
        ? `${opt.hint} Achtung: Dafür ist noch kein passender Sensor in den Optimum Watt-Integrationseinstellungen hinterlegt.`
        : opt.hint;
    };
    updateHint();

    select.addEventListener("change", (e) => {
      this._draft.threshold_basis = e.target.value;
      updateHint();
    });
  }

  _renderMinSocHint(wrap) {
    const hint = wrap.querySelector("#em-f-min-soc-hint");
    const state = this._latestState || {};
    const base = "Solange der Speicher nicht mindestens so weit geladen ist, springt das Gerät nicht an (0/leer = keine Einschränkung). Ausnahme: Wird schon tatsächlich ins Netz eingespeist und deckt das allein die Einschaltschwelle, gilt das Limit nicht.";
    hint.textContent = state.has_storage_soc_entity
      ? base
      : `${base} Achtung: Dafür ist noch kein Speicher-Ladestand-Sensor in den Optimum Watt-Integrationseinstellungen hinterlegt.`;
  }

  static getStubConfig() {
    return { type: "custom:optimum-watt-card" };
  }
}

customElements.define("optimum-watt-card", OptimumWattCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "optimum-watt-card",
  name: "Optimum Watt",
  description: "PV-Überschuss-Kaskadensteuerung: Geräte anlegen, priorisieren und live steuern.",
});

/**
 * Full-page wrapper around optimum-watt-card, used as the sidebar panel so the
 * interface is reachable with a single click without building a dashboard.
 */
class OptimumWattPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this._card) {
      // A panel_custom element gets no automatic toolbar or sidebar-toggle
      // from Home Assistant - those only exist on built-in panels that
      // include their own <app-toolbar>. Without our own menu button here,
      // there is no way to bring the sidebar back on a narrow/mobile screen
      // once it's closed. Fill exactly the allocated area and scroll
      // internally - a 100vh host pushes our own header off-screen too.
      this.style.display = "block";
      this.style.height = "100%";
      this.style.boxSizing = "border-box";
      this.style.overflow = "auto";
      this.style.background = "var(--primary-background-color)";

      const header = document.createElement("div");
      header.style.cssText =
        "display:flex;align-items:center;gap:8px;padding:8px 12px;position:sticky;top:0;z-index:1;background:var(--app-header-background-color, var(--primary-background-color));";
      const menuBtn = document.createElement("button");
      menuBtn.setAttribute("aria-label", "Menü");
      menuBtn.title = "Menü";
      menuBtn.style.cssText =
        "border:none;background:transparent;color:var(--primary-text-color);cursor:pointer;width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;";
      const menuIcon = document.createElement("ha-icon");
      menuIcon.setAttribute("icon", "mdi:menu");
      menuBtn.appendChild(menuIcon);
      menuBtn.addEventListener("click", () => {
        this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
      });
      header.appendChild(menuBtn);

      const wrap = document.createElement("div");
      wrap.style.maxWidth = "680px";
      wrap.style.margin = "0 auto";
      wrap.style.padding = "0 16px 16px";

      this._card = document.createElement("optimum-watt-card");
      this._card.setConfig({});
      wrap.appendChild(this._card);
      this.appendChild(header);
      this.appendChild(wrap);
    }
    this._card.hass = hass;
  }

  set panel(panel) {}

  set narrow(narrow) {}

  set route(route) {}
}

customElements.define("optimum-watt-panel", OptimumWattPanel);
