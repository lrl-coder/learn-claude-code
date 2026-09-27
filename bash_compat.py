"""Locate and invoke Bash consistently across supported platforms."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def find_bash() -> str | None:
    configured = os.getenv("BASH_PATH")
    if configured:
        return configured

    discovered = shutil.which("bash")
    if discovered:
        return discovered

    if os.name == "nt":
        candidates = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "Git" / "bin" / "bash.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
            / "Git" / "bin" / "bash.exe",
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Programs" / "Git" / "bin" / "bash.exe",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)

    return None


def bash_argv(command: str) -> list[str]:
    executable = find_bash()
    if not executable:
        raise FileNotFoundError(
            "Bash not found. Install Git Bash or set BASH_PATH."
        )
    return [executable, "-lc", command]
