from __future__ import annotations

import json
import os
import stat
from enum import Enum


class TimeFormat(Enum):
    ISO_8601 = "8601"
    EPOCH = "epoch"
    EPOCH_MS = "epoch_ms"
    YYYY_MM_DD = "YYYY-MM-DD"


def _restrict_permissions(path: str, directory: bool = False) -> None:
    """Best effort: make a secrets file/directory readable by its owner only (no-op where unsupported)."""
    try:
        os.chmod(path, stat.S_IRWXU if directory else (stat.S_IRUSR | stat.S_IWUSR))
    except OSError:
        pass


def _make_private_dir(path: str) -> None:
    """Create a directory (if missing) that only the owner can access."""
    if path and not os.path.isdir(path):
        os.makedirs(path, mode=0o700, exist_ok=True)
        _restrict_permissions(path, directory=True)


def _create_private_file(path: str) -> None:
    """Create an empty owner-only file if it does not exist, and tighten it if it does."""
    try:
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
    except OSError:
        return
    _restrict_permissions(path)


def save_env_global(app_key: str, app_secret: str, callback_url: str) -> None:
    """
    Save global credentials to ~/.schwabdev/env.json (keys: app_key, app_secret, callback_url).
    The file is created so that only the current user can read it.
    """
    env_path = os.path.expanduser("~/.schwabdev/env.json")
    _make_private_dir(os.path.dirname(env_path))
    _restrict_permissions(os.path.dirname(env_path), directory=True)
    fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"app_key": app_key, "app_secret": app_secret, "callback_url": callback_url}, f, indent=4)
    _restrict_permissions(env_path)
