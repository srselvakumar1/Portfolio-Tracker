"""Small per-user preferences (theme, text size), stored as JSON.

They live in ~/Library/Application Support/PTracker/settings.json for both the
installed app and a run from source, so the choice follows the person, not
the database. Writes go to a temporary file first and are then renamed, so a
crash can never leave a half-written settings file.
"""

import json
import os

SETTINGS_DIR = os.path.expanduser("~/Library/Application Support/PTracker")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings.json")

DEFAULTS = {
    "theme": "light",        # "light", "dark" or "system" (match macOS)
    "text_size": "normal",   # "small", "normal", "large" or "xlarge"
}

CHOICES = {
    "theme": ("light", "dark", "system"),
    "text_size": ("small", "normal", "large", "xlarge"),
}


def load_settings() -> dict:
    """Return the saved settings merged over the defaults (bad values are ignored)."""
    settings = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            for key, value in saved.items():
                if key in CHOICES and value not in CHOICES[key]:
                    continue
                settings[key] = value
    except (OSError, ValueError):
        pass
    return settings


def save_settings(updates: dict) -> dict:
    """Merge `updates` into the saved settings and write them atomically."""
    settings = load_settings()
    settings.update(updates)
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    os.replace(tmp, SETTINGS_PATH)
    return settings
