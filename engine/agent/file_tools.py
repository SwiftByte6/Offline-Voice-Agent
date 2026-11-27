"""Bounded local file tools used by the desktop agent."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Any
import webbrowser

MAX_SEARCH_ENTRIES = 20_000
MAX_SEARCH_RESULTS = 20


class FileToolError(ValueError):
    """Raised when a file action falls outside the user-accessible workspace."""


def _roots() -> tuple[Path, ...]:
    home = Path.home().resolve()
    candidates = (home / "Desktop", home / "Downloads", home / "Documents", home / "Pictures")
    return tuple(path.resolve() for path in candidates if path.exists())


def _allowed_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    if not any(path == root or root in path.parents for root in _roots()):
        raise FileToolError("File actions are limited to Desktop, Downloads, Documents, and Pictures.")
    return path


def search_files(query: str, location: str = "downloads") -> dict[str, Any]:
    """Find matching files in a common user folder without scanning the whole drive."""
    root_map = {root.name.lower(): root for root in _roots()}
    root = root_map.get(location.strip().lower())
    if root is None:
        raise FileToolError("Search location must be Desktop, Downloads, Documents, or Pictures.")

    terms = [term for term in query.casefold().split() if term]
    if not terms:
        raise FileToolError("search_files requires a query.")

    results: list[dict[str, str]] = []
    visited = 0
    for directory, _, filenames in os.walk(root):
        for filename in filenames:
            visited += 1
            if visited > MAX_SEARCH_ENTRIES or len(results) >= MAX_SEARCH_RESULTS:
                break
            if all(term in filename.casefold() for term in terms):
                path = Path(directory) / filename
                results.append({"path": str(path), "name": filename})
        if visited > MAX_SEARCH_ENTRIES or len(results) >= MAX_SEARCH_RESULTS:
            break

    return {"success": True, "matches": results, "searched": str(root)}


def rename_file(source: str, new_name: str, overwrite: bool = False) -> dict[str, Any]:
    path = _allowed_path(source)
    if not path.is_file():
        raise FileToolError("The source file does not exist.")
    clean_name = Path(new_name).name.strip()
    if not clean_name or clean_name in {".", ".."}:
        raise FileToolError("A valid new file name is required.")
    destination = path.with_name(clean_name)
    if destination.exists() and not overwrite:
        return {"success": False, "requires_confirmation": True, "destination": str(destination)}
    if destination.exists():
        destination.unlink()
    path.rename(destination)
    return {"success": True, "message": f"renamed to {destination.name}", "path": str(destination)}


def move_file(source: str, destination_dir: str, overwrite: bool = False) -> dict[str, Any]:
    path = _allowed_path(source)
    destination_root = _allowed_path(destination_dir)
    if not path.is_file() or not destination_root.is_dir():
        raise FileToolError("The source file or destination folder does not exist.")
    destination = destination_root / path.name
    if destination.exists() and not overwrite:
        return {"success": False, "requires_confirmation": True, "destination": str(destination)}
    if destination.exists():
        destination.unlink()
    shutil.move(str(path), str(destination))
    return {"success": True, "message": f"moved to {destination}", "path": str(destination)}


def copy_file(source: str, destination_dir: str, overwrite: bool = False) -> dict[str, Any]:
    path = _allowed_path(source)
    destination_root = _allowed_path(destination_dir)
    if not path.is_file() or not destination_root.is_dir():
        raise FileToolError("The source file or destination folder does not exist.")
    destination = destination_root / path.name
    if destination.exists() and not overwrite:
        return {"success": False, "requires_confirmation": True, "destination": str(destination)}
    if destination.exists():
        destination.unlink()
    shutil.copy2(path, destination)
    return {"success": True, "message": f"copied to {destination}", "path": str(destination)}


def delete_file(source: str) -> dict[str, Any]:
    path = _allowed_path(source)
    if not path.is_file():
        raise FileToolError("The file does not exist.")
    path.unlink()
    return {"success": True, "message": f"deleted {path.name}"}


def open_file(source: str) -> dict[str, Any]:
    path = _allowed_path(source)
    if not path.exists():
        raise FileToolError("The file does not exist.")
    os.startfile(str(path))
    return {"success": True, "message": f"opened {path.name}"}


def open_url(url: str) -> dict[str, Any]:
    if not url.startswith(("https://", "http://")):
        raise FileToolError("open_url requires an http or https URL.")
    webbrowser.open(url, new=2)
    return {"success": True, "message": f"opened {url}"}
