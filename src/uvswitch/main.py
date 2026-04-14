"""uvswitch - Switch uv versions based on pyproject.toml [tool.uv] required-version."""

from __future__ import annotations

import os
import platform as _platform
import re
import shutil
import stat
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

# tomllib is stdlib in Python 3.11+; fall back to regex parsing for older versions
if sys.version_info >= (3, 11):
    import tomllib
else:
    tomllib = None  # type: ignore[assignment]

UV_RELEASES_BASE = "https://github.com/astral-sh/uv/releases/download"
UVSWITCH_HOME = Path.home() / ".uvswitch"
VERSIONS_DIR = UVSWITCH_HOME / "versions"
BIN_DIR = UVSWITCH_HOME / "bin"


# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------


def _platform_triple() -> tuple[str, str]:
    """Return (platform_triple, archive_ext) for the current machine."""
    system = _platform.system().lower()
    machine = _platform.machine().lower()

    if system == "darwin":
        arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
        return f"{arch}-apple-darwin", "tar.gz"
    elif system == "linux":
        arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
        # prefer the musl build for maximum portability; falls back gracefully
        return f"{arch}-unknown-linux-musl", "tar.gz"
    elif system == "windows":
        return "x86_64-pc-windows-msvc", "zip"
    else:
        raise SystemExit(f"Unsupported platform: {system}")


def _bin_name() -> str:
    return "uv.exe" if _platform.system().lower() == "windows" else "uv"


# ---------------------------------------------------------------------------
# pyproject.toml parsing
# ---------------------------------------------------------------------------


def _find_pyproject() -> Path | None:
    """Walk up from cwd until pyproject.toml is found."""
    path = Path.cwd()
    while True:
        candidate = path / "pyproject.toml"
        if candidate.exists():
            return candidate
        parent = path.parent
        if parent == path:
            return None
        path = parent


def _read_required_version(pyproject: Path) -> str | None:
    """Return the raw [tool.uv] required-version string, or None."""
    if tomllib is not None:
        with open(pyproject, "rb") as fh:
            data = tomllib.load(fh)
        return data.get("tool", {}).get("uv", {}).get("required-version")
    # Regex fallback for Python < 3.11
    text = pyproject.read_text(encoding="utf-8")
    # Grab everything inside [tool.uv] up to the next section header
    section = re.search(r"\[tool\.uv\](.*?)(?=\n\s*\[|\Z)", text, re.DOTALL)
    if not section:
        return None
    match = re.search(r'required-version\s*=\s*["\']([^"\']+)["\']', section.group(1))
    return match.group(1) if match else None


def _extract_min_version(spec: str) -> str | None:
    """
    Extract the minimum (lower-bound) version from a PEP 440 specifier string.

    Examples:
        ">=0.5.0"            -> "0.5.0"
        "==0.5.1"            -> "0.5.1"
        "~=0.5.0"            -> "0.5.0"
        "0.5.0"              -> "0.5.0"
        ">=0.4.0,<1.0.0"    -> "0.4.0"
    """
    spec = spec.strip()
    ver_pat = re.compile(
        r"^(>=|==|~=|>|!=|<=|<)?\s*(\d+\.\d+(?:\.\d+)*(?:[._-]?\w+)*)$"
    )
    # Prefer == and >= operators; fall back to first parseable part
    candidates: list[tuple[str, str]] = []
    for part in spec.split(","):
        m = ver_pat.match(part.strip())
        if m:
            candidates.append((m.group(1) or "", m.group(2)))

    for op, ver in candidates:
        if op in ("==", ">=", "~=", ""):
            return ver
    # Last resort: any parseable version
    return candidates[0][1] if candidates else None


# ---------------------------------------------------------------------------
# Download & cache
# ---------------------------------------------------------------------------


def _cached_bin(version: str) -> Path | None:
    """Return the cached uv binary path if it already exists."""
    path = VERSIONS_DIR / version / _bin_name()
    return path if path.exists() else None


def _download_and_extract(version: str) -> Path:
    """Download uv *version* into VERSIONS_DIR and return path to the binary."""
    triple, ext = _platform_triple()
    asset = f"uv-{triple}.{ext}"
    url = f"{UV_RELEASES_BASE}/{version}/{asset}"

    version_dir = VERSIONS_DIR / version
    version_dir.mkdir(parents=True, exist_ok=True)
    archive_path = version_dir / asset
    bin_path = version_dir / _bin_name()

    print(f"Downloading uv {version} …")
    try:
        urllib.request.urlretrieve(url, archive_path)
    except urllib.error.HTTPError as exc:
        # Clean up empty dir so a retry isn't blocked
        shutil.rmtree(version_dir, ignore_errors=True)
        raise SystemExit(
            f"Download failed ({exc.code}): {url}\n"
            "Check that the version exists: https://github.com/astral-sh/uv/releases"
        ) from exc
    except urllib.error.URLError as exc:
        shutil.rmtree(version_dir, ignore_errors=True)
        raise SystemExit(f"Network error: {exc.reason}") from exc

    # Extract the 'uv' binary from the archive
    if ext == "tar.gz":
        with tarfile.open(archive_path, "r:gz") as tar:
            for member in tar.getmembers():
                # The binary lives at either `uv` (flat) or `uv-<triple>/uv` (nested)
                if member.name == "uv" or member.name.endswith("/uv"):
                    member_file = tar.extractfile(member)
                    if member_file:
                        bin_path.write_bytes(member_file.read())
                    break
            else:
                shutil.rmtree(version_dir, ignore_errors=True)
                raise SystemExit(f"Could not find 'uv' binary inside {asset}")
    elif ext == "zip":
        with zipfile.ZipFile(archive_path) as zf:
            for name in zf.namelist():
                if name == "uv.exe" or name.endswith("/uv.exe"):
                    bin_path.write_bytes(zf.read(name))
                    break
            else:
                shutil.rmtree(version_dir, ignore_errors=True)
                raise SystemExit(f"Could not find 'uv.exe' inside {asset}")

    archive_path.unlink(missing_ok=True)

    # Ensure the binary is executable
    mode = bin_path.stat().st_mode
    bin_path.chmod(mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    return bin_path


def _ensure_version(version: str) -> Path:
    """Return path to the uv binary for *version*, downloading if needed."""
    cached = _cached_bin(version)
    if cached:
        return cached
    return _download_and_extract(version)


# ---------------------------------------------------------------------------
# Symlink management
# ---------------------------------------------------------------------------


def _active_version() -> str | None:
    """Return the version string managed by uvswitch, or None."""
    link = BIN_DIR / _bin_name()
    if not link.is_symlink():
        return None
    target = link.resolve()
    # Path is  ~/.uvswitch/versions/<version>/uv
    return target.parent.name


def _switch(version: str) -> None:
    """Point the managed symlink at *version*, downloading if required."""
    bin_path = _ensure_version(version)

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    link = BIN_DIR / _bin_name()

    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(bin_path)

    print(f"Switched to uv {version}")
    _warn_if_not_on_path()


def _warn_if_not_on_path() -> None:
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    if str(BIN_DIR) not in path_dirs:
        shell = Path(os.environ.get("SHELL", "")).name
        if shell in ("zsh", "bash"):
            print(
                f"\nAdd uvswitch to your PATH by adding this to your shell config:\n"
                f'  export PATH="{BIN_DIR}:$PATH"'
            )
        else:
            print(f"\nAdd {BIN_DIR} to the front of your PATH to activate uvswitch.")


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------


def _cmd_switch(version_arg: str | None) -> None:
    if version_arg:
        version = version_arg.lstrip("v")  # tolerate "v0.5.0"
    else:
        pyproject = _find_pyproject()
        if pyproject is None:
            raise SystemExit(
                "No pyproject.toml found in the current directory or any parent.\n"
                "Specify a version explicitly: uvswitch <version>"
            )

        spec = _read_required_version(pyproject)
        if not spec:
            raise SystemExit(
                f"No [tool.uv] required-version found in {pyproject}\n\n"
                "Add one to your pyproject.toml:\n"
                "  [tool.uv]\n"
                '  required-version = ">=0.5.0"'
            )

        version = _extract_min_version(spec)
        if not version:
            raise SystemExit(f"Could not parse a version from specifier: {spec!r}")

        print(f"Found required-version = {spec!r}  →  using {version}")

    _switch(version)


def _cmd_current() -> None:
    ver = _active_version()
    if ver is None:
        print("No uv version is currently managed by uvswitch.")
        print(f"(expected symlink at {BIN_DIR / _bin_name()})")
    else:
        link = BIN_DIR / _bin_name()
        print(f"uv {ver}  →  {link.resolve()}")


def _cmd_list() -> None:
    if not VERSIONS_DIR.exists() or not any(VERSIONS_DIR.iterdir()):
        print("No uv versions installed by uvswitch.")
        return

    current = _active_version()
    versions = sorted(
        (d for d in VERSIONS_DIR.iterdir() if d.is_dir()),
        key=lambda d: d.name,
    )
    for v in versions:
        marker = " *" if v.name == current else "  "
        print(f"{marker} {v.name}")


def _cmd_uninstall(version: str) -> None:
    version = version.lstrip("v")
    version_dir = VERSIONS_DIR / version
    if not version_dir.exists():
        raise SystemExit(f"uv {version} is not installed.")
    if _active_version() == version:
        raise SystemExit(
            f"uv {version} is currently active; switch to another version first."
        )
    shutil.rmtree(version_dir)
    print(f"Removed uv {version}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    # Manual dispatch: avoid argparse conflicts between subcommands and bare version args.
    argv = sys.argv[1:]

    if not argv:
        _cmd_switch(None)
        return

    if argv[0] in ("-h", "--help"):
        print(
            "usage: uvswitch [version | list | current | uninstall <version>]\n"
            "\n"
            "Switch the active uv binary based on pyproject.toml [tool.uv] required-version.\n"
            "\n"
            "commands:\n"
            "  <version>              Switch to a specific uv version (e.g. 0.5.4)\n"
            "  (no args)              Read version from nearest pyproject.toml\n"
            "  list  (ls)             List installed uv versions  (* = active)\n"
            "  current                Show the currently active uv version\n"
            "  uninstall <version>    Remove a cached uv version\n"
            "\n"
            "examples:\n"
            "  uvswitch               # read required-version from pyproject.toml\n"
            "  uvswitch 0.5.4         # switch to uv 0.5.4\n"
            "  uvswitch list          # show installed versions\n"
            "  uvswitch current       # show active version\n"
            "  uvswitch uninstall 0.4.0\n"
        )
        return

    cmd = argv[0]

    if cmd in ("list", "ls"):
        _cmd_list()
    elif cmd == "current":
        _cmd_current()
    elif cmd == "uninstall":
        if len(argv) < 2:
            raise SystemExit("usage: uvswitch uninstall <version>")
        _cmd_uninstall(argv[1])
    else:
        # Treat as a version string
        _cmd_switch(cmd)


if __name__ == "__main__":
    main()
