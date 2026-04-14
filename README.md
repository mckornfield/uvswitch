# uvswitch

A lightweight, zero-dependency version manager for [uv](https://github.com/astral-sh/uv). Automatically switches to the `uv` version pinned in your project's `pyproject.toml`.

## Installation

Install directly from GitHub using `pip` or `uv`:

```bash
pip install git+https://github.com/mckornfield/uvswitch.git
```

```bash
uv tool install git+https://github.com/mckornfield/uvswitch.git
```

### Add to PATH

After installation, add the managed binary directory to your shell's PATH so that `uv` resolves through uvswitch:

```bash
# Add to ~/.bashrc or ~/.zshrc
export PATH="$HOME/.uvswitch/bin:$PATH"
```

Reload your shell or run `source ~/.bashrc` / `source ~/.zshrc` to apply.

## How it works

uvswitch reads the `required-version` field from `[tool.uv]` in the nearest `pyproject.toml` (searching from the current directory up through parent directories), downloads and caches the matching `uv` binary under `~/.uvswitch/versions/`, and updates the symlink at `~/.uvswitch/bin/uv` to point to it.

```
~/.uvswitch/
├── bin/
│   └── uv          ← symlink to the active version
└── versions/
    ├── 0.5.0/uv
    ├── 0.5.4/uv
    └── 0.6.0/uv
```

Subsequent switches to an already-downloaded version are instant — no network request needed.

## Pinning the uv version in a project

In your project's `pyproject.toml`, add:

```toml
[tool.uv]
required-version = ">=0.5.0"
```

uvswitch supports standard PEP 440 version specifiers:

| Specifier | Version used |
|-----------|-------------|
| `>=0.5.0` | `0.5.0` |
| `==0.5.1` | `0.5.1` |
| `~=0.5.0` | `0.5.0` |
| `>=0.4.0,<1.0.0` | `0.4.0` |
| `0.5.0` | `0.5.0` |

## Usage

### Auto-switch from pyproject.toml

```bash
cd /path/to/your/project
uvswitch
# Found required-version = ">=0.5.0"  →  using 0.5.0
# Switched to uv 0.5.0
```

### Switch to a specific version

```bash
uvswitch 0.6.0
uvswitch v0.6.0    # "v" prefix is accepted
```

### List installed versions

```bash
uvswitch list
#  * 0.5.0
#    0.5.4
#    0.6.0
```

The active version is marked with `*`.

### Show the active version

```bash
uvswitch current
# uv 0.5.0  →  /Users/you/.uvswitch/versions/0.5.0/uv
```

### Uninstall a cached version

```bash
uvswitch uninstall 0.4.0
# Removed uv 0.4.0
```

You cannot uninstall the currently active version — switch to another version first.

## Platform support

uvswitch automatically selects the correct binary for your platform:

| OS | Architecture | Format |
|----|-------------|--------|
| macOS | ARM64, x86_64 | `.tar.gz` |
| Linux | ARM64, x86_64 (musl) | `.tar.gz` |
| Windows | x86_64 | `.zip` |

## Requirements

- Python 3.9+
- No external dependencies

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.
