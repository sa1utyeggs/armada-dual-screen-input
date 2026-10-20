"""Supported pages and compatibility for saved modes removed from the UI."""
SUPPORTED_MODES = ("trackpad", "split", "keyboard", "position", "preferences")
LEGACY_MODES = ("settings", "mirror")


def normalize_mode(mode: object) -> str | None:
    if mode in LEGACY_MODES:
        return "split"
    return mode if mode in SUPPORTED_MODES else None
