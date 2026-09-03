"""The Optimum Watt integration."""
from __future__ import annotations

import hashlib
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, PLATFORMS
from .coordinator import OptimumWattCoordinator
from .services import async_register_services
from .ws_api import async_register_websocket_commands

CARD_URL_BASE = f"/{DOMAIN}_files"
CARD_FILENAME = "optimum-watt-card.js"
PANEL_URL_PATH = "optimum_watt"

# Optimum Watt is only ever set up via the UI config flow, never through YAML.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the websocket API and services once, independent of any entry."""
    hass.data.setdefault(DOMAIN, {})
    async_register_websocket_commands(hass)
    await async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Optimum Watt from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = OptimumWattCoordinator(hass, entry)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await _async_register_frontend(hass)

    return True


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the custom Lovelace card and sidebar panel, once for all entries."""
    if hass.data[DOMAIN].get("_frontend_registered"):
        return

    www_dir = Path(__file__).parent / "www"
    card_path = www_dir / CARD_FILENAME
    await hass.http.async_register_static_paths(
        [StaticPathConfig(f"{CARD_URL_BASE}/{CARD_FILENAME}", str(card_path), False)]
    )

    # Cache-bust on the actual file content, not just the manifest version -
    # otherwise browsers and the mobile app's WebView keep serving a stale
    # cached copy of the card after an update until the user manually clears
    # their cache, since the URL never changes on its own.
    card_bytes = await hass.async_add_executor_job(card_path.read_bytes)
    cache_bust = hashlib.sha256(card_bytes).hexdigest()[:10]
    card_url = f"{CARD_URL_BASE}/{CARD_FILENAME}?v={cache_bust}"

    add_extra_js_url(hass, card_url)

    await async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name="optimum-watt-panel",
        sidebar_title="Optimum Watt",
        sidebar_icon="mdi:flash",
        module_url=card_url,
        embed_iframe=False,
        require_admin=False,
    )

    hass.data[DOMAIN]["_frontend_registered"] = True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: OptimumWattCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator.async_unload()
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the persisted device list along with the config entry."""
    await OptimumWattCoordinator.async_remove_storage(hass, entry.entry_id)
