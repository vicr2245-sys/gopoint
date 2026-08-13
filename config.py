"""
Reads API keys from the environment (loaded from .env via python-dotenv)
and builds the list of providers that are actually usable. This is what
makes adding/removing a provider a config change, not a code change.
"""
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values, load_dotenv, set_key, unset_key

from core.providers.base import RouteProvider
from core.providers.mapbox_provider import MapboxProvider
from core.providers.nominatim_provider import NominatimProvider
from core.providers.ors_provider import ORSProvider
from core.providers.osrm_provider import OSRMProvider

# Keys the Settings dialog knows how to read/write. Anything else a user
# has hand-added to .env (OSRM_BASE_URL, NOMINATIM_USER_AGENT, ...) is left
# completely untouched by save_env_values below.
MANAGED_ENV_KEYS = ("ANTHROPIC_API_KEY", "ORS_API_KEY", "MAPBOX_API_KEY", "APP_THEME")


def get_app_theme() -> str:
    """Returns 'dark' or 'light', defaulting to 'light'."""
    theme = os.environ.get("APP_THEME", "").lower()
    if theme in ("dark", "light"):
        return theme
    env_values = read_current_env_values()
    theme = env_values.get("APP_THEME", "").lower()
    if theme in ("dark", "light"):
        return theme
    return "light"


def _app_dir() -> Path:
    """
    Directory to look for .env in. When running as a normal script, that's
    this file's own folder (repo root). When frozen into a PyInstaller
    build, python-dotenv's default search (based on the calling frame's
    file) can end up pointed at a temp extraction path instead of the
    actual folder the .exe lives in — so when frozen, we explicitly use
    the executable's own directory instead, since that's where build.bat
    copies env.example.txt and where a user would sensibly keep their .env
    right next to the .exe.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


load_dotenv(dotenv_path=_app_dir() / ".env")


def diagnose_env_setup() -> Optional[str]:
    """
    If neither ORS nor Mapbox is configured, checks WHY and returns a
    specific, actionable message — rather than letting the app silently
    fall back to OSRM-only mode when the user actually believes they set
    up a key. Returns None if at least one is configured (nothing to
    report).

    Specifically checks for the most common way this goes wrong: Windows
    File Explorer hides known file extensions by default, so renaming
    env.example.txt to .env can silently leave a file literally named
    ".env.txt" that looks identical to ".env" with extensions hidden —
    we've hit this exact gotcha before in this project.
    """
    if os.environ.get("ORS_API_KEY") or os.environ.get("MAPBOX_API_KEY"):
        return None

    app_dir = _app_dir()
    env_path = app_dir / ".env"
    if env_path.exists():
        # The file exists but the keys inside it aren't being picked up —
        # more likely a formatting issue (quotes, stray spaces, wrong
        # variable name) than a missing/misnamed file.
        return (
            f"Found a .env file at {env_path}, but no ORS_API_KEY or "
            f"MAPBOX_API_KEY value was read from it. Double-check the file "
            f"contents: no quotes around the value, no extra spaces around "
            f"the '=', and the variable name spelled exactly as ORS_API_KEY."
        )

    misnamed_txt = app_dir / ".env.txt"
    if misnamed_txt.exists():
        return (
            f"Found '.env.txt' instead of '.env' in {app_dir} — Windows "
            f"likely kept a hidden '.txt' extension when you renamed the "
            f"file (File Explorer hides known extensions by default, so "
            f"this is easy to miss). Rename it to exactly '.env' — run "
            f"'dir /a' in that folder from a terminal to see the real "
            f"filename if you're unsure."
        )

    return (
        f"No .env file found in {app_dir}. Copy env.example.txt to .env "
        f"there and fill in your API keys. Running without one for now — "
        f"basic routing still works via the free OSRM/Nominatim providers, "
        f"just without elevation charts or surface composition."
    )


def mask_key(value: str) -> str:
    """Shows just enough of a key to recognize it without displaying the
    whole secret — e.g. 'sk-a…8f2c'. Used only for display, never for
    anything functional."""
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}…{value[-4:]}"


def read_current_env_values() -> dict[str, str]:
    """
    Returns the currently-saved values (read from the .env file on disk,
    not just the running process's os.environ) for the keys the Settings
    dialog manages, so it can show what's already configured without the
    user having to remember or re-check a text file.
    """
    env_path = _app_dir() / ".env"
    if not env_path.exists():
        return {}
    values = dotenv_values(env_path)
    return {key: value for key, value in values.items() if key in MANAGED_ENV_KEYS and value}


def save_env_values(updates: dict[str, str]) -> Path:
    """
    Writes the given key/value pairs into .env next to the app, preserving
    any other existing lines/comments/variables untouched — including ones
    this module doesn't manage (OSRM_BASE_URL, etc.) and ones in
    MANAGED_ENV_KEYS that simply aren't present in `updates` this time.

    A key mapped to an empty string is removed from the file entirely
    (lets a key be cleared, not just overwritten) rather than being
    written as `KEY=`. Also applies the change to the current process's
    os.environ immediately, so code that reads it directly (e.g. the
    Anthropic client) picks up the change without needing a restart.
    """
    env_path = _app_dir() / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    if not env_path.exists():
        env_path.touch()

    for key, value in updates.items():
        if value:
            set_key(str(env_path), key, value, quote_mode="never")
            os.environ[key] = value
        else:
            unset_key(str(env_path), key)
            os.environ.pop(key, None)

    return env_path


def get_configured_providers() -> tuple[list[RouteProvider], list[RouteProvider]]:
    """
    Returns (routing_providers, geocode_providers).

    ORS is the primary provider (routing + elevation + surface data, no
    card needed for its free tier) and Mapbox is optional (its free tier
    requires a card even though it doesn't charge you). Neither is
    strictly required to run the app at all, though: OSRM needs no key,
    and Nominatim (always included below) covers its geocoding — so with
    zero API keys configured, the app still runs on OSRM + Nominatim
    alone. You lose elevation charts, surface composition, and the
    distance/elevation-targeting accuracy work that's ORS-specific, but
    basic point-to-point and loop routing still works with nothing to
    sign up for.
    """
    providers: list[RouteProvider] = []

    if os.environ.get("ORS_API_KEY"):
        providers.append(ORSProvider())

    if os.environ.get("MAPBOX_API_KEY"):
        providers.append(MapboxProvider())

    # Always included — free, no key, no signup. Previously this was only
    # added when ORS or Mapbox was ALSO configured (since OSRM alone can't
    # geocode), but Nominatim below already covers geocoding regardless of
    # which routing providers are active, so that restriction wasn't
    # actually necessary and just blocked a fully keyless setup.
    providers.append(OSRMProvider())

    # Nominatim is geocoding-only, free, no signup — always include it as
    # an extra fallback for resolving place names, independent of which
    # routing providers are configured.
    geocode_providers: list[RouteProvider] = [NominatimProvider()]

    return providers, geocode_providers
