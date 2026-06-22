"""Kollar om en nyare release finns på GitHub."""
import os
import requests

REPO = "Cebbas/kvitto-appen"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
VERSION_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "VERSION")


def current_version() -> str:
    try:
        with open(VERSION_FILE, "r") as f:
            return f.read().strip()
    except OSError:
        return "0.0.0"


def _parse(version: str):
    return tuple(int(p) for p in version.lstrip("v").split("."))


def check_for_update(timeout: float = 4.0):
    """Returnerar (uppdatering_finns, senaste_version, release_url) eller (False, None, None) vid fel."""
    try:
        resp = requests.get(RELEASES_API, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        latest = data["tag_name"].lstrip("v")
        url = data.get("html_url", f"https://github.com/{REPO}/releases/latest")
        if _parse(latest) > _parse(current_version()):
            return True, latest, url
        return False, latest, url
    except Exception:
        return False, None, None
