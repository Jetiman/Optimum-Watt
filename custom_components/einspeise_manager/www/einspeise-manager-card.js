/**
 * Einspeise-Manager Lovelace card.
 * Plain Web Component, no build step, no external dependencies -
 * safe to load directly as a frontend module by the integration.
 */

const FALLBACK_STAGE_ICON = "mdi:radiator";

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

class EinspeiseManagerCard extends HTMLElement {
  setConfig(config) {
    if (!config.surplus_entity) {
      throw new Error("einspeise-manager-card: 'surplus_entity' fehlt in der Konfiguration");
    }
    if (!Array.isArray(config.stages) || config.stages.length === 0) {
      throw new Error("einspeise-manager-card: 'stages' fehlt oder ist leer");
    }
    this._config = config;
    this._built = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) {
      this._buildStaticShell();
      this._built = true;
    }
    this._update();
  }

  getCardSize() {
    return 2 + (this._config?.stages?.length || 3);
  }

  connectedCallback() {
    if (this._built) this._update();
  }

  _state(entityId) {
    return this._hass?.states?.[entityId];
  }

  _buildStaticShell() {
    const style = document.createElement("style");
    style.textContent = `
      ha-card { padding: 16px; }
      .em-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
      .em-title { font-size: 1.1em; font-weight: 500; }
      .em-surplus { display: flex; align-items: baseline; gap: 8px; margin-bottom: 16px; }
      .em-surplus .value { font-size: 2em; font-weight: 600; }
      .em-surplus .label { color: var(--secondary-text-color); font-size: 0.9em; }
      .em-stage { border-radius: 10px; padding: 10px 12px; margin-bottom: 8px; background: var(--secondary-background-color, #f2f2f2); display: flex; align-items: center; gap: 10px; }
      .em-stage.on { background: var(--success-color, #43a047); color: white; }
      .em-stage.pending { background: var(--warning-color, #fb8c00); color: white; }
      .em-stage ha-icon { --mdc-icon-size: 26px; }
      .em-stage-main { flex: 1; min-width: 0; }
      .em-stage-name { font-weight: 500; }
      .em-stage-sub { font-size: 0.85em; opacity: 0.85; }
      .em-modes { display: flex; gap: 4px; }
      .em-modes button { border: none; border-radius: 6px; padding: 4px 8px; font-size: 0.75em; cursor: pointer; background: rgba(0,0,0,0.12); color: inherit; }
      .em-modes button.active { background: rgba(255,255,255,0.9); color: #222; font-weight: 600; }
      .em-threshold { display: flex; align-items: center; gap: 4px; font-size: 0.8em; margin-top: 4px; }
      .em-threshold input { width: 64px; border-radius: 4px; border: 1px solid rgba(0,0,0,0.2); padding: 2px 4px; }
      .em-auto-toggle { cursor: pointer; }
    `;

    const card = document.createElement("ha-card");
    card.innerHTML = `
      <div class="em-header">
        <div class="em-title">${this._config.title || "Einspeise-Manager"}</div>
        <ha-icon class="em-auto-toggle" id="em-auto-icon"></ha-icon>
      </div>
      <div class="em-surplus">
        <div class="value" id="em-surplus-value">–</div>
        <div class="label">Einspeisung aktuell</div>
      </div>
      <div id="em-stages"></div>
    `;

    this._root = document.createElement("div");
    this._root.appendChild(style);
    this._root.appendChild(card);

    this.innerHTML = "";
    this.appendChild(this._root);

    this._els = {
      autoIcon: card.querySelector("#em-auto-icon"),
      surplusValue: card.querySelector("#em-surplus-value"),
      stages: card.querySelector("#em-stages"),
    };

    this._els.autoIcon.addEventListener("click", () => {
      if (!this._config.auto_entity) return;
      this._hass.callService("switch", "toggle", {
        entity_id: this._config.auto_entity,
      });
    });
  }

  _update() {
    const surplusState = this._state(this._config.surplus_entity);
    const surplusW = surplusState ? Number(surplusState.state) : null;
    this._els.surplusValue.textContent = fmtPower(surplusW);

    if (this._config.auto_entity) {
      const autoOn = this._state(this._config.auto_entity)?.state === "on";
      this._els.autoIcon.setAttribute(
        "icon",
        autoOn ? "mdi:toggle-switch" : "mdi:toggle-switch-off-outline"
      );
      this._els.autoIcon.style.color = autoOn
        ? "var(--success-color, #43a047)"
        : "var(--disabled-text-color, #9e9e9e)";
    }

    this._els.stages.innerHTML = "";
    for (const stage of this._config.stages) {
      this._els.stages.appendChild(this._renderStage(stage));
    }
  }

  _renderStage(stage) {
    const statusState = this._state(stage.status_entity);
    const modeState = this._state(stage.mode_entity);
    const thresholdState = this._state(stage.threshold_entity);
    const status = statusState?.state || "unbekannt";
    const mode = modeState?.state || "auto";
    const remaining = statusState?.attributes?.verbleibende_sekunden;
    const active = statusState?.attributes?.aktiv;

    const el = document.createElement("div");
    el.className = "em-stage";
    if (active) el.classList.add("on");
    else if (remaining !== null && remaining !== undefined) el.classList.add("pending");

    let sub = status;
    const remainingText = fmtSeconds(remaining);
    if (remainingText) {
      sub += active ? ` · schaltet in ${remainingText} ab` : ` · schaltet in ${remainingText} ein`;
    }

    el.innerHTML = `
      <ha-icon icon="${stage.icon || FALLBACK_STAGE_ICON}"></ha-icon>
      <div class="em-stage-main">
        <div class="em-stage-name">${stage.name}</div>
        <div class="em-stage-sub">${sub}</div>
        ${
          thresholdState
            ? `<div class="em-threshold">Schwelle:
                 <input type="number" step="50" value="${thresholdState.state}" data-threshold-entity="${stage.threshold_entity}"/> W
               </div>`
            : ""
        }
      </div>
      <div class="em-modes">
        <button data-mode="auto" data-entity="${stage.mode_entity}" class="${mode === "auto" ? "active" : ""}">Auto</button>
        <button data-mode="on" data-entity="${stage.mode_entity}" class="${mode === "on" ? "active" : ""}">An</button>
        <button data-mode="off" data-entity="${stage.mode_entity}" class="${mode === "off" ? "active" : ""}">Aus</button>
      </div>
    `;

    el.querySelectorAll("button[data-mode]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const entityId = btn.getAttribute("data-entity");
        if (!entityId) return;
        this._hass.callService("select", "select_option", {
          entity_id: entityId,
          option: btn.getAttribute("data-mode"),
        });
      });
    });

    const thresholdInput = el.querySelector("input[data-threshold-entity]");
    if (thresholdInput) {
      thresholdInput.addEventListener("change", () => {
        this._hass.callService("number", "set_value", {
          entity_id: thresholdInput.getAttribute("data-threshold-entity"),
          value: Number(thresholdInput.value),
        });
      });
      thresholdInput.addEventListener("click", (ev) => ev.stopPropagation());
    }

    return el;
  }

  static getStubConfig(hass) {
    const entities = Object.keys(hass?.states || {});
    const surplus = entities.find((e) => e.startsWith("sensor.") && e.includes("ueberschuss"));
    const auto = entities.find((e) => e.startsWith("switch.") && e.includes("automatik"));
    return {
      type: "custom:einspeise-manager-card",
      title: "Einspeise-Manager",
      surplus_entity: surplus || "sensor.einspeise_manager_ueberschuss",
      auto_entity: auto || "switch.einspeise_manager_automatik",
      stages: [
        {
          name: "Heizung 1",
          status_entity: "sensor.einspeise_manager_heizung_1_status",
          mode_entity: "select.einspeise_manager_heizung_1_modus",
          threshold_entity: "number.einspeise_manager_heizung_1_einschaltschwelle",
        },
        {
          name: "Heizung 2",
          status_entity: "sensor.einspeise_manager_heizung_2_status",
          mode_entity: "select.einspeise_manager_heizung_2_modus",
          threshold_entity: "number.einspeise_manager_heizung_2_einschaltschwelle",
        },
        {
          name: "Heizung 3",
          status_entity: "sensor.einspeise_manager_heizung_3_status",
          mode_entity: "select.einspeise_manager_heizung_3_modus",
          threshold_entity: "number.einspeise_manager_heizung_3_einschaltschwelle",
        },
      ],
    };
  }
}

customElements.define("einspeise-manager-card", EinspeiseManagerCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "einspeise-manager-card",
  name: "Einspeise-Manager Karte",
  description: "Kaskadierte Überschusssteuerung für Warmwasser-Heizstäbe (Shelly 4PM & Co.)",
});
