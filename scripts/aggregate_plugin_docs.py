#!/usr/bin/env python3
"""Aggregate the plugin repos' documentation into the core Sphinx site.

    scripts/aggregate_plugin_docs.py [--source git|local] [--local-root DIR]

Reads ``docs/plugins_manifest.yml``, brings each listed repo's ``docs/guide.md``
and ``docs/images/`` into ``docs/plugins/<slug>/``, rewrites the guide's
outward-facing links into internal cross-references, and generates
``docs/plugins/index.md`` (roster tables + toctree) — the page that replaced the
hand-maintained ``plugins_list.md``.

``docs/plugins/`` is a build artifact: it is regenerated wholesale on every run
and is git-ignored. Nothing is ever written back into a plugin repo.

Sources:
  --source git    (default) shallow-clone each repo at its manifest ``ref``.
  --source local  copy from sibling checkouts under --local-root
                  (default ../adl-plugins), for offline work on this machine.

The conventions a guide must follow — front matter, image naming, link forms —
are documented in docs-plan/README.md, "Aggregation conventions". Violations are
reported here as errors with a file and line, and exit 1.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
MANIFEST = DOCS_DIR / "plugins_manifest.yml"
OUT_DIR = DOCS_DIR / "plugins"

# A core-docs link in a guide, written as a real URL so it also works when the
# guide is read in its own repo on GitHub. Rewritten to an internal xref here.
#   https://adl-tool.readthedocs.io/en/latest/user_guide/foo.html#bar
#   -> /user_guide/foo.md#bar
CORE_URL_RE = re.compile(
    r"https?://(?P<host>[\w.-]*readthedocs\.io)"
    r"(?:/(?P<lang>[a-z]{2}(?:_[A-Z]{2})?)/(?P<version>[\w.-]+))?"
    r"/(?P<path>[\w/-]+)\.html(?P<anchor>#[\w-]+)?"
)

# A sibling-plugin guide link, written as a GitHub blob URL for the same reason.
#   https://github.com/wmo-raf/adl-ftp-plugin/blob/main/docs/guide.md#bar
#   -> /plugins/adl-ftp-plugin/guide.md#bar   (when that plugin is aggregated)
PLUGIN_URL_RE = re.compile(
    r"https?://github\.com/(?P<org>[\w.-]+)/(?P<slug>[\w.-]+)"
    r"/blob/(?P<ref>[\w.-]+)/docs/guide\.md(?P<anchor>#[\w-]+)?"
)

IMAGE_RE = re.compile(r"!\[[^\]]*\]\((?P<path>[^)\s]+)\)")
FRONT_MATTER_RE = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)


@dataclass
class Plugin:
    slug: str
    repo: str
    ref: str
    documented: bool
    meta: dict = field(default_factory=dict)
    guide_body: str = ""

    @property
    def repo_url(self) -> str:
        return re.sub(r"\.git$", "", self.repo)

    @property
    def releases_url(self) -> str:
        return f"{self.repo_url}/releases"

    @property
    def name(self) -> str:
        return self.meta.get("name") or self.slug

    @property
    def category(self) -> str:
        return self.meta.get("category", "general")


class Problems:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.notices: list[str] = []

    def error(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")

    def notice(self, where: str, msg: str) -> None:
        self.notices.append(f"{where}: {msg}")


def load_manifest() -> tuple[str, list[Plugin]]:
    data = yaml.safe_load(MANIFEST.read_text())
    canonical = data["canonical_docs_url"].rstrip("/")
    plugins = []
    for entry in data["plugins"]:
        repo = entry["repo"]
        slug = re.sub(r"\.git$", "", repo.rstrip("/").rsplit("/", 1)[-1])
        documented = bool(entry.get("docs", False))
        meta = {
            k: v
            for k, v in entry.items()
            if k not in {"repo", "ref", "docs"} and v is not None
        }
        plugins.append(
            Plugin(
                slug=slug,
                repo=repo,
                ref=entry.get("ref", "main"),
                documented=documented,
                meta=meta,
            )
        )
    return canonical, plugins


def fetch_docs(plugin: Plugin, source: str, local_root: Path, workdir: Path) -> Path | None:
    """Return the path to the plugin repo's docs/ directory, or None."""
    if source == "local":
        docs = local_root / plugin.slug / "docs"
        return docs if docs.is_dir() else None

    dest = workdir / plugin.slug
    cmd = [
        "git", "clone", "--depth", "1", "--branch", plugin.ref,
        "--single-branch", plugin.repo, str(dest),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"clone failed for {plugin.slug} at ref {plugin.ref}:\n{result.stderr}"
        )
    docs = dest / "docs"
    return docs if docs.is_dir() else None


def parse_front_matter(text: str, where: str, problems: Problems) -> tuple[dict, str]:
    match = FRONT_MATTER_RE.match(text)
    if not match:
        problems.error(where, "no YAML front matter; an aggregated guide needs an "
                              "`adl_plugin:` block (see Aggregation conventions)")
        return {}, text
    try:
        loaded = yaml.safe_load(match.group("body")) or {}
    except yaml.YAMLError as exc:
        problems.error(where, f"front matter is not valid YAML: {exc}")
        return {}, text[match.end():]
    meta = loaded.get("adl_plugin")
    if not isinstance(meta, dict):
        problems.error(where, "front matter has no `adl_plugin:` mapping")
        meta = {}
    for required in ("name", "connects_to", "category"):
        if not meta.get(required):
            problems.error(where, f"front matter is missing `adl_plugin.{required}`")
    if meta.get("category") == "country" and not meta.get("country"):
        problems.error(where, "category `country` requires `adl_plugin.country`")
    return meta, text  # keep front matter in the copied file; MyST ignores it


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def rewrite_links(
    text: str,
    plugin: Plugin,
    canonical: str,
    aggregated: set[str],
    problems: Problems,
) -> str:
    where = f"{plugin.slug}/docs/guide.md"
    canonical_host = canonical.split("//", 1)[-1]

    def core_sub(m: re.Match) -> str:
        line = line_of(text, m.start())
        if m.group("host") != canonical_host:
            problems.error(
                f"{where}:{line}",
                f"core-docs link points at {m.group('host')}, not the canonical "
                f"docs host {canonical_host}; left unrewritten and it will 404",
            )
            return m.group(0)
        path = m.group("path")
        target = DOCS_DIR / f"{path}.md"
        if not target.exists():
            problems.error(
                f"{where}:{line}",
                f"core-docs link targets /{path}.html, which has no page in the "
                f"core docs ({target.relative_to(REPO_ROOT)} not found)",
            )
            return m.group(0)
        return f"/{path}.md{m.group('anchor') or ''}"

    def plugin_sub(m: re.Match) -> str:
        line = line_of(text, m.start())
        slug = re.sub(r"\.git$", "", m.group("slug"))
        if slug == plugin.slug:
            problems.error(
                f"{where}:{line}",
                "guide links to its own guide by URL; use an in-page anchor",
            )
            return m.group(0)
        if slug in aggregated:
            return f"/plugins/{slug}/guide.md{m.group('anchor') or ''}"
        problems.notice(
            f"{where}:{line}",
            f"link to {slug}'s guide stays external — that plugin is not "
            f"aggregated yet (docs: false, or absent from the manifest)",
        )
        return m.group(0)

    text = CORE_URL_RE.sub(core_sub, text)
    text = PLUGIN_URL_RE.sub(plugin_sub, text)
    return text


def check_images(
    text: str,
    plugin: Plugin,
    docs_dir: Path,
    image_owners: dict[str, str],
    problems: Problems,
) -> None:
    where = f"{plugin.slug}/docs/guide.md"
    referenced: set[str] = set()
    for m in IMAGE_RE.finditer(text):
        path = m.group("path")
        line = line_of(text, m.start())
        if path.startswith(("http://", "https://", "/")):
            problems.error(
                f"{where}:{line}",
                f"image `{path}` is not a repo-relative path; guides must "
                f"reference their own images/ directory",
            )
            continue
        if not path.startswith("images/") or ".." in path:
            problems.error(
                f"{where}:{line}",
                f"image `{path}` must live under images/ in the plugin repo",
            )
            continue
        name = path[len("images/"):]
        if not (docs_dir / "images" / name).exists():
            problems.error(f"{where}:{line}", f"image `{path}` does not exist")
        referenced.add(name)

    images_dir = docs_dir / "images"
    if images_dir.is_dir():
        for image in sorted(images_dir.iterdir()):
            if not image.is_file():
                continue
            # Sphinx pools every image into one _images/ directory and silently
            # renames on collision, so two plugins must never ship the same
            # basename. Filenames are prefixed per plugin to keep them apart.
            owner = image_owners.get(image.name)
            if owner is not None and owner != plugin.slug:
                problems.error(
                    f"{plugin.slug}/docs/images/{image.name}",
                    f"filename collides with {owner}'s image of the same name; "
                    f"image filenames must be unique across the aggregated site",
                )
            image_owners[image.name] = plugin.slug
            if image.name not in referenced:
                problems.notice(
                    f"{plugin.slug}/docs/images/{image.name}",
                    "captured but not referenced by the guide",
                )


def check_headings(text: str, plugin: Plugin, problems: Problems) -> None:
    """One H1, and no two headings at the same level sharing a slug.

    myst_heading_anchors makes every h1-h3 an anchor target; two headings that
    slug the same silently get -1 suffixes, so a link written against the
    obvious slug lands on the wrong one.
    """
    where = f"{plugin.slug}/docs/guide.md"
    h1s: list[tuple[int, str]] = []
    slugs: dict[str, int] = {}
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,3}) +(.*?)\s*$", line)
        if not m:
            continue
        level, title = len(m.group(1)), m.group(2)
        if level == 1:
            h1s.append((lineno, title))
        slug = re.sub(r"[^\w\- ]", "", title.lower()).strip().replace(" ", "-")
        if slug in slugs:
            problems.error(
                f"{where}:{lineno}",
                f"heading {title!r} slugs to `#{slug}`, already used at line "
                f"{slugs[slug]}; anchors to it are ambiguous",
            )
        else:
            slugs[slug] = lineno
    if len(h1s) != 1:
        problems.error(
            where,
            f"a guide must have exactly one H1 (its title); found {len(h1s)}",
        )
    elif plugin.meta.get("name") and h1s[0][1] != plugin.meta["name"]:
        # The H1 titles the page; adl_plugin.name titles the sidebar entry and
        # the index row. Two spellings of one plugin reads as two plugins.
        problems.error(
            f"{where}:{h1s[0][0]}",
            f"H1 {h1s[0][1]!r} does not match `adl_plugin.name` "
            f"{plugin.meta['name']!r}; they must be the same string",
        )


def copy_plugin(
    plugin: Plugin,
    docs_dir: Path,
    canonical: str,
    aggregated: set[str],
    image_owners: dict[str, str],
    problems: Problems,
) -> bool:
    guide = docs_dir / "guide.md"
    if not guide.exists():
        problems.error(
            f"{plugin.slug}/docs",
            "manifest says docs: true but there is no docs/guide.md",
        )
        return False

    text = guide.read_text()
    meta, text = parse_front_matter(text, f"{plugin.slug}/docs/guide.md", problems)
    plugin.meta = {**plugin.meta, **meta}
    check_headings(text, plugin, problems)
    check_images(text, plugin, docs_dir, image_owners, problems)
    text = rewrite_links(text, plugin, canonical, aggregated, problems)

    dest = OUT_DIR / plugin.slug
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "guide.md").write_text(text)
    images = docs_dir / "images"
    if images.is_dir():
        shutil.copytree(images, dest / "images", dirs_exist_ok=True)
    plugin.guide_body = text
    return True


def table(rows: list[list[str]], headers: list[str]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_index(canonical: str, plugins: list[Plugin]) -> str:
    def link(p: Plugin) -> str:
        return f"**{p.name}**"

    def guide_cell(p: Plugin) -> str:
        if p.documented:
            return f"[Guide]({p.slug}/guide.md)"
        return f"[Repository]({p.repo_url}) — guide not written yet"

    general = [p for p in plugins if p.category == "general"]
    country = [p for p in plugins if p.category == "country"]

    general_rows = [
        [
            link(p),
            p.meta.get("connects_to", "").strip(),
            guide_cell(p),
            f"`{p.repo}`",
            f"[Releases]({p.releases_url})",
        ]
        for p in general
    ]
    country_rows = [
        [
            link(p),
            f"{p.meta.get('country_flag', '')} {p.meta.get('country', '')}".strip(),
            p.meta.get("connects_to", "").strip(),
            guide_cell(p),
            f"`{p.repo}`",
        ]
        for p in country
    ]

    choose = [
        f"**{p.meta['choose_when'].strip()}**\n→ "
        + (
            f"See the [{p.name} guide]({p.slug}/guide.md)."
            if p.documented
            else f"Use the [{p.name}]({p.repo_url})."
        )
        for p in plugins
        if p.meta.get("choose_when")
    ]

    # Explicit titles so the sidebar and the tables above agree on a name,
    # whatever the guide chose for its H1.
    toctree = "\n".join(
        f"{p.name} <{p.slug}/guide>" for p in plugins if p.documented
    )

    return f"""# 🧩 Available Plugins

ADL is a plugin-based system. The core application handles scheduling,
storage, unit conversion, QC, and dispatch — but it collects no observation
data on its own. You install one or more plugins depending on which AWS
vendor or data source your NMHS uses.

This page lists all currently available plugins. If none of these match your
data source, see [Developing Plugins](/developer_guide/plugins/index.md) to
build your own.

```{{note}}
This page and the plugin guides below are generated at build time from each
plugin's own repository — see `docs/plugins_manifest.yml` in the ADL core
repository for the roster. Plugins without a guide link are documented in
their repository README while their guide is being written.
```

---

## How to Read This Page

Each plugin entry shows:

- **What it connects to** — the upstream data source or vendor
- **Guide** — the configuration and troubleshooting guide for that plugin
- **Install URL** — the GitHub repository URL to use with `ADL_PLUGIN_GIT_REPOS`
  or the `install-plugin` command
- **Releases** — link to the GitHub Releases page where you can find version
  tags for pinned installs

For installation instructions see
[Installation](/installation.md#6-install-plugins).

---

## General Plugins

These plugins work across multiple countries and vendor deployments.

{table(general_rows, ["Plugin", "Connects to", "Guide", "Install URL", "Releases"])}

---

## Country-Specific FTP Decoders

These plugins extend the ADL FTP Plugin with custom decoders for specific
national deployments. They are maintained by individual NMHSs and are not
part of the core ADL project.

```{{note}}
Country-specific decoders are used **alongside** the ADL FTP Plugin, not
instead of it. Install the FTP Plugin first, then install the relevant
decoder for your country.
```

{table(country_rows, ["Plugin", "Country", "Description", "Guide", "Install URL"])}

---

## Choosing the Right Plugin

Not sure which plugin you need? Use this guide:

{(chr(10)*2).join(choose)}

**None of the above match your data source**
→ See [Developing Plugins](/developer_guide/plugins/index.md) to build a
custom plugin for your vendor.

---

## Installing a Plugin

**Build-time (recommended for production)** — pin to a release tag for
reproducible deployments:

```bash
# In your .env file
ADL_PLUGIN_GIT_REPOS=https://github.com/wmo-raf/adl-ftp-plugin.git#0.13.0
```

Then rebuild:

```bash
make build
make up
```

**Runtime** — install into a running stack without rebuilding:

```bash
docker compose exec adl install-plugin --git https://github.com/wmo-raf/adl-ftp-plugin.git#0.13.0
```

For full installation details and all available options see
[Installation](/installation.md#6-install-plugins).

---

## NMHSs Currently Using ADL

For a full list of NMHSs currently using ADL see the
[project README](https://github.com/wmo-raf/adl#nmhss-using-adl).

## Plugin Guides

```{{toctree}}
---
maxdepth: 1
titlesonly: true
---
{toctree}
```
"""


def run_sphinx(outdir: Path) -> int:
    """Build the site and gate on warnings coming from the plugin tree.

    The core docs carry pre-existing warnings (screenshots not yet regenerated),
    so -W would fail for reasons unrelated to aggregation. Gate on the plugins/
    tree only: an aggregated guide must build clean.
    """
    result = subprocess.run(
        [sys.executable, "-m", "sphinx", "-b", "html", str(DOCS_DIR), str(outdir)],
        capture_output=True,
        text=True,
    )
    sys.stderr.write(result.stderr)
    if result.returncode != 0:
        print("sphinx-build failed", file=sys.stderr)
        return result.returncode

    plugin_warnings = [
        line
        for line in result.stderr.splitlines()
        if "WARNING" in line and f"{OUT_DIR}{os.sep}" in line
    ]
    if plugin_warnings:
        print(
            f"{len(plugin_warnings)} warning(s) from aggregated plugin docs:",
            file=sys.stderr,
        )
        for line in plugin_warnings:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"sphinx-build clean for {OUT_DIR.relative_to(REPO_ROOT)}; output in {outdir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("git", "local"), default="git")
    parser.add_argument(
        "--local-root",
        default=str(REPO_ROOT.parent / "adl-plugins"),
        help="directory holding plugin checkouts, for --source local",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat notices as errors too",
    )
    parser.add_argument(
        "--build",
        metavar="OUTDIR",
        help="run sphinx-build into OUTDIR afterwards and fail on any warning "
             "raised from the aggregated docs/plugins/ tree",
    )
    args = parser.parse_args()

    canonical, plugins = load_manifest()
    aggregated = {p.slug for p in plugins if p.documented}
    image_owners: dict[str, str] = {}
    problems = Problems()

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)

    local_root = Path(args.local_root).resolve()
    with tempfile.TemporaryDirectory(prefix="adl-plugin-docs-") as tmp:
        for plugin in plugins:
            if not plugin.documented:
                continue
            docs_dir = fetch_docs(plugin, args.source, local_root, Path(tmp))
            if docs_dir is None:
                problems.error(
                    plugin.slug,
                    f"no docs/ directory found ({args.source} source)",
                )
                continue
            copy_plugin(
                plugin, docs_dir, canonical, aggregated, image_owners, problems
            )

    (OUT_DIR / "index.md").write_text(render_index(canonical, plugins))

    for notice in problems.notices:
        print(f"notice: {notice}", file=sys.stderr)
    for error in problems.errors:
        print(f"error: {error}", file=sys.stderr)

    documented = [p for p in plugins if p.documented]
    print(
        f"aggregated {len(documented)} plugin guide(s) into "
        f"{OUT_DIR.relative_to(REPO_ROOT)} "
        f"({len(problems.errors)} error(s), {len(problems.notices)} notice(s))"
    )
    if problems.errors or (args.strict and problems.notices):
        return 1

    if args.build:
        return run_sphinx(Path(args.build))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
