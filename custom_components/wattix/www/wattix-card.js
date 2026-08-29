/**
 * Wattix Lovelace card.
 *
 * Plain Web Component, no build step, no external dependencies. Talks to
 * the integration's websocket API (wattix/*) to list, add,
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

function fmtHours(seconds) {
  if (seconds === null || seconds === undefined) return "–";
  const h = seconds / 3600;
  return (Math.round(h * 10) / 10).toString().replace(".", ",");
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

class WattixCard extends HTMLElement {
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
    return this._editingId !== null && this._editingId !== undefined || this._addingNew;
  }

  async _ensureEntryId() {
    if (this._entryId) return;
    if (this._config.entry_id) {
      this._entryId = this._config.entry_id;
      return;
    }
    try {
      const entries = await this._hass.callWS({ type: "config_entries/get" });
      const match = entries.find((e) => e.domain === "wattix");
      if (match) this._entryId = match.entry_id;
    } catch (err) {
      // ignore, handled by the "not configured" empty state below
    }
  }

  async _subscribe() {
    if (!this._hass || this._subscribed) return;
    await this._ensureEntryId();
    if (!this._entryId) {
      this._renderError("Keine Wattix-Instanz gefunden.");
      return;
    }
    this._subscribed = true;
    this._unsubscribe = await this._hass.connection.subscribeMessage(
      (state) => {
        this._latestState = state;
        this._render();
      },
      { type: "wattix/subscribe", entry_id: this._entryId }
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
    this._callWS({ type: "wattix/set_auto_mode", enabled });
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
    this._callWS({ type: "wattix/update_device", device_id: deviceId, mode });
  }

  _moveDevice(deviceId, direction) {
    const ids = this._latestState.devices.map((d) => d.id);
    const idx = ids.indexOf(deviceId);
    const swapIdx = idx + direction;
    if (swapIdx < 0 || swapIdx >= ids.length) return;
    [ids[idx], ids[swapIdx]] = [ids[swapIdx], ids[idx]];
    this._callWS({ type: "wattix/reorder_devices", device_ids: ids });
  }

  _deleteDevice(deviceId, name) {
    if (!window.confirm(`Gerät "${name}" wirklich löschen?`)) return;
    this._callWS({ type: "wattix/remove_device", device_id: deviceId });
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
      hysteresis_w: "100",
      min_runtime_minutes: "",
      min_runtime_deadline: "",
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
      min_runtime_minutes: device.min_runtime_s ? String(device.min_runtime_s / 60) : "",
      min_runtime_deadline: device.min_runtime_deadline || "",
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
      on_delay_s: Math.round(Number(d.on_delay_min) * 60),
      off_delay_s: Math.round(Number(d.off_delay_min) * 60),
      min_runtime_s: useMinRuntime ? Math.round(minutes * 60) : 0,
      min_runtime_deadline: useMinRuntime ? d.min_runtime_deadline : "",
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
      this._callWS({ type: "wattix/add_device", ...payload });
    } else {
      this._callWS({ type: "wattix/update_device", device_id: this._editingId, ...payload });
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
      .em-logo { display: flex; align-items: flex-end; gap: 8px; }
      .em-logo-bars { display: flex; align-items: flex-end; gap: 3px; height: 20px; }
      .em-logo-bar { width: 5px; border-radius: 2px 2px 1px 1px; }
      .em-logo-bar.b1 { height: 33%; background: #3C4550; }
      .em-logo-bar.b2 { height: 52%; background: #B96A2C; }
      .em-logo-bar.b3 { height: 72%; background: #D98A3D; }
      .em-logo-bar.b4 { height: 100%; background: #F5A623; }
      .em-logo-word { font-size: 1.15em; font-weight: 700; letter-spacing: -0.01em; color: var(--primary-text-color); }
      .em-header-right { display: flex; align-items: center; gap: 10px; }
      .em-active-count { color: var(--secondary-text-color); font-size: 0.9em; }
      .em-auto-toggle { cursor: pointer; }
      .em-surplus { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; }
      .em-surplus .value { font-size: 2em; font-weight: 600; }
      .em-surplus .label { color: var(--secondary-text-color); font-size: 0.9em; }
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
      .em-device.disabled { opacity: 0.55; }
      .em-device ha-icon { --mdc-icon-size: 24px; flex-shrink: 0; }
      .em-device-order { display: flex; flex-direction: column; gap: 2px; }
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
      .em-form-row input { border-radius: 6px; border: 1px solid var(--divider-color, #ccc); padding: 6px 8px; background: var(--card-background-color); color: var(--primary-text-color); width: 100%; box-sizing: border-box; min-width: 0; }
      .em-form { min-width: 0; }
      #em-f-entity-wrap, #em-f-entity-wrap ha-entity-picker { width: 100%; box-sizing: border-box; }
      .em-form-advanced { margin-bottom: 10px; }
      .em-form-advanced summary { cursor: pointer; font-size: 0.85em; color: var(--secondary-text-color); }
      .em-form-hint { font-size: 0.78em; color: var(--secondary-text-color); margin: -4px 0 4px; }
      .em-form-actions { display: flex; gap: 8px; justify-content: flex-end; }
      .em-btn-primary { background: var(--primary-color); color: var(--text-primary-color, white); border: none; border-radius: 6px; padding: 8px 14px; cursor: pointer; font-weight: 500; }
      .em-btn-secondary { background: transparent; color: var(--secondary-text-color); border: none; border-radius: 6px; padding: 8px 14px; cursor: pointer; }
    `;

    const titleHtml = this._config.title
      ? `<div class="em-title">${escapeHtml(this._config.title)}</div>`
      : `
        <div class="em-logo" aria-label="Wattix">
          <span class="em-logo-bars">
            <span class="em-logo-bar b1"></span>
            <span class="em-logo-bar b2"></span>
            <span class="em-logo-bar b3"></span>
            <span class="em-logo-bar b4"></span>
          </span>
          <span class="em-logo-word">Wattix</span>
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
      <div class="em-legend">
        <span class="em-legend-item"><span class="em-legend-dot on"></span>An</span>
        <span class="em-legend-item"><span class="em-legend-dot pending"></span>Wartet</span>
        <span class="em-legend-item"><span class="em-legend-dot catchup"></span>Pflichtlauf</span>
        <span class="em-legend-item"><span class="em-legend-dot disabled"></span>Regelung aus</span>
      </div>
      <div id="em-devices"></div>
      <button class="em-add-btn" id="em-add-btn">+ Gerät hinzufügen</button>
    `;

    this._root = document.createElement("div");
    this._root.appendChild(style);
    this._root.appendChild(card);

    this.innerHTML = "";
    this.appendChild(this._root);

    this._els = {
      autoIcon: card.querySelector("#em-auto-icon"),
      surplusValue: card.querySelector("#em-surplus-value"),
      activeCount: card.querySelector("#em-active-count"),
      devices: card.querySelector("#em-devices"),
      addBtn: card.querySelector("#em-add-btn"),
    };

    this._els.autoIcon.addEventListener("click", () => this._toggleAuto());
    this._els.addBtn.addEventListener("click", () => this._openAdd());
  }

  _render() {
    const state = this._latestState;
    if (!state) return;

    this._els.surplusValue.textContent = fmtPower(state.surplus_w);
    this._els.activeCount.textContent = `${state.regulated_count} / ${state.devices.length} geregelt`;
    this._els.autoIcon.setAttribute(
      "icon",
      state.auto_mode ? "mdi:toggle-switch" : "mdi:toggle-switch-off-outline"
    );
    this._els.autoIcon.style.color = state.auto_mode
      ? "var(--success-color, #43a047)"
      : "var(--disabled-text-color, #9e9e9e)";

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
    else if (device.catchup_active) el.classList.add("catchup");
    else if (device.active) el.classList.add("on");
    else if (pending) el.classList.add("pending");

    let sub = `${STATUS_LABELS[device.status] || device.status} · ${fmtPower(device.power_w)}`;
    const remainingText = fmtSeconds(device.remaining_seconds);
    if (remainingText) {
      sub += device.active ? ` · schaltet in ${remainingText} ab` : ` · schaltet in ${remainingText} ein`;
    }
    if (device.min_runtime_s) {
      sub += ` · ${fmtHours(device.runtime_today_s)}/${fmtHours(device.min_runtime_s)}h bis ${device.min_runtime_deadline}`;
    }

    el.innerHTML = `
      <div class="em-device-order">
        <button class="em-icon-btn" data-action="up" ${idx === 0 ? "disabled" : ""} title="Höhere Priorität">▲</button>
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
        <button data-mode="disabled" class="${device.mode === "disabled" ? "active" : ""}" title="Wattix fasst diesen Schalter nicht an">Regelung aus</button>
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
        <p class="em-form-hint">Wird die Mindestlaufzeit sonst nicht erreicht, schaltet Wattix notfalls auch ohne Überschuss ein, rechtzeitig vor der Uhrzeit.</p>
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
    wrap.querySelector("#em-f-min-runtime").addEventListener("input", (e) => (this._draft.min_runtime_minutes = e.target.value));
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

  static getStubConfig() {
    return { type: "custom:wattix-card" };
  }
}

customElements.define("wattix-card", WattixCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "wattix-card",
  name: "Wattix",
  description: "PV-Überschuss-Kaskadensteuerung: Geräte anlegen, priorisieren und live steuern.",
});

/**
 * Full-page wrapper around wattix-card, used as the sidebar panel so the
 * interface is reachable with a single click without building a dashboard.
 */
class WattixPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this._card) {
      // Fill exactly the area Home Assistant already allocates for the panel
      // (viewport minus its own toolbar) and scroll internally - a 100vh
      // host pushes that toolbar (and its sidebar-toggle button) off-screen.
      this.style.display = "block";
      this.style.height = "100%";
      this.style.boxSizing = "border-box";
      this.style.overflow = "auto";
      this.style.padding = "16px";
      this.style.background = "var(--primary-background-color)";

      const wrap = document.createElement("div");
      wrap.style.maxWidth = "680px";
      wrap.style.margin = "0 auto";

      this._card = document.createElement("wattix-card");
      this._card.setConfig({});
      wrap.appendChild(this._card);
      this.appendChild(wrap);
    }
    this._card.hass = hass;
  }

  set panel(panel) {}

  set narrow(narrow) {}

  set route(route) {}
}

customElements.define("wattix-panel", WattixPanel);
