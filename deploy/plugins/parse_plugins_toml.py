#!/usr/bin/env python3
"""
Parse an ADL plugins.toml manifest and emit install_plugin.sh argument strings,
one per enabled plugin. Output is read line-by-line by utils.sh and the Dockerfile.

Output per enabled plugin (one line, space-delimited args):
    --git https://github.com/org/repo.git#v1.2.0
    --url https://example.com/plugin.tar.gz
    --url https://example.com/plugin.tar.gz --hash abc123def
    --folder /path/to/local/plugin
    --dev --folder /path/to/local/plugin   (when dev = true)

Usage:
    parse_plugins_toml.py <manifest.toml>
"""
import sys

try:
    import tomllib  # Python 3.11+ stdlib
except ImportError:
    try:
        import tomli as tomllib  # backport for Python 3.10
    except ImportError:
        print(
            "ERROR: Neither tomllib (Python 3.11+) nor tomli package is available. "
            'Add \'tomli; python_version < "3.11"\' to requirements.txt.',
            file=sys.stderr,
        )
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print("Usage: parse_plugins_toml.py <manifest.toml>", file=sys.stderr)
        sys.exit(1)
    
    manifest_file = sys.argv[1]
    
    try:
        with open(manifest_file, "rb") as f:  # tomllib requires binary mode
            config = tomllib.load(f)
    except FileNotFoundError:
        sys.exit(0)  # caller logs "no manifest found"
    except tomllib.TOMLDecodeError as e:
        print(
            f"ERROR: Failed to parse plugins manifest '{manifest_file}': {e}",
            file=sys.stderr,
        )
        sys.exit(1)
    
    if not config or "plugins" not in config:
        sys.exit(0)
    
    for i, plugin in enumerate(config.get("plugins") or [], 1):
        if not plugin.get("enabled", True):
            name = plugin.get("name", f"plugin #{i}")
            print(f"SKIP {name}", file=sys.stderr)
            continue
        
        name = plugin.get("name", f"plugin #{i}")
        
        if "git" in plugin:
            repo = plugin["git"]
            if "tag" in plugin:
                repo = f"{repo}#{plugin['tag']}"
            line = f"--git {repo}"
            if "hash" in plugin:
                line += f" --hash {plugin['hash']}"
            print(line)
        
        elif "url" in plugin:
            line = f"--url {plugin['url']}"
            if "hash" in plugin:
                line += f" --hash {plugin['hash']}"
            print(line)

        elif "folder" in plugin:
            dev_flag = "--dev " if plugin.get("dev", False) else ""
            print(f"{dev_flag}--folder {plugin['folder']}")

        else:
            print(
                f"WARNING: '{name}' has no 'git', 'url', or 'folder' key — skipping.",
                file=sys.stderr,
            )


if __name__ == "__main__":
    main()
