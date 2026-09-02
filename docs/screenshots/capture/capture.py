"""
The ADL documentation screenshot runner (docs plan, decision 5).

Executes a declarative ``screenshots.yml`` against a running, seeded ADL
instance with Playwright and writes one PNG per entry. Plugin repos and the
core docs carry only the YAML; this is the single piece of capture code.

    python capture.py docs/screenshots.yml --base-url http://localhost:8765 \
        --repo-dir ../adl-plugins/adl-ftp-plugin [--lang en,fr] [--only name]

Manifest format::

    defaults:                      # file level
      viewport: [1440, 900]
      padding: 12
      wait: 1000                   # ms to settle after navigation (optional)
    screenshots:
    - name: ftp-connection-form    # output: <images-dir>/<name>.png
      url: /networkftp/edit/1/     # relative to the base URL
      auth: true                   # optional; false = no admin session (login page)
      setup:                       # optional, ordered; a wait_for sits right
        - click: "sel"             #   after the action it waits on
        - wait_for: "sel"
        - hover: "sel"
        - fill: { selector: "sel", value: "..." }
        - select: { selector: "sel", value: "..." }
        - upload: { selector: "sel", path: "relative/to/repo" }
        - wait: 500                # ms
        - eval: "javascript"       # escape hatch for DOM surgery
      callouts:                    # optional; numbers only, never text
        - badge: { target: "sel", n: 1 }
        - highlight: "sel"         # or { target: "sel" }
      capture:
        selector: "sel"            # crop; omit for the viewport
        padding: 12                # overrides defaults
        full_page: false

A name may include a sub-path (``user/monitoring/x``). Images directory: ``--images-dir`` or, under ``--repo-dir``, ``docs/_static/images``
when it exists (the core docs) else ``docs/images`` (a plugin). Languages other
than the first are written as ``<name>.<lang>.png`` — Sphinx's default
``figure_language_filename`` — after switching the admin user's preferred
language through the account settings page, which is how the Wagtail admin
picks its language.
"""

import argparse
import sys
from pathlib import Path

import yaml
from playwright.sync_api import Error as PlaywrightError, sync_playwright

HERE = Path(__file__).resolve().parent
ANNOTATE_JS = (HERE / "annotate.js").read_text()


class CaptureError(Exception):
    pass


def load_manifest(path):
    data = yaml.safe_load(Path(path).read_text()) or {}
    if isinstance(data, list):
        raise CaptureError(
            f"{path}: flat list manifests are no longer supported — "
            "use 'defaults:' + 'screenshots:' entries with name/url/setup/callouts/capture")
    defaults = {"viewport": [1440, 900], "padding": 12, "wait": 1000}
    defaults.update(data.get("defaults") or {})
    entries = data.get("screenshots") or []
    for entry in entries:
        for key in ("name", "url"):
            if key not in entry:
                raise CaptureError(f"{path}: an entry is missing '{key}': {entry}")
    return defaults, entries


def images_dir_for(repo_dir, explicit):
    if explicit:
        return Path(explicit)
    for candidate in ("docs/_static/images", "docs/images"):
        if (repo_dir / candidate).exists():
            return repo_dir / candidate
    return repo_dir / "docs/images"


class Runner:
    def __init__(self, browser, base_url, defaults, repo_dir, images_dir, username, password):
        self.browser = browser
        self.base_url = base_url.rstrip("/")
        self.defaults = defaults
        self.repo_dir = repo_dir
        self.images_dir = images_dir
        self.username = username
        self.password = password
        self.storage_state = None

    # -- session -----------------------------------------------------------------

    def new_context(self, auth):
        w, h = self.defaults["viewport"]
        kwargs = {"viewport": {"width": w, "height": h}, "device_scale_factor": 1}
        if auth:
            if self.storage_state is None:
                self.storage_state = self.login()
            kwargs["storage_state"] = self.storage_state
        context = self.browser.new_context(**kwargs)
        context.add_init_script(ANNOTATE_JS)
        return context

    def login(self):
        w, h = self.defaults["viewport"]
        context = self.browser.new_context(viewport={"width": w, "height": h})
        page = context.new_page()
        page.goto(f"{self.base_url}/login/")
        page.fill("#id_username", self.username)
        page.fill("#id_password", self.password)
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")
        if "/login/" in page.url:
            raise CaptureError("login failed — check the admin credentials")
        state = context.storage_state()
        context.close()
        return state

    def set_language(self, lang):
        """Switch the admin user's preferred language — the Wagtail admin
        renders in it — through the same account page an operator uses.

        Raises rather than carrying on in the wrong language: a French run
        that silently produced English images would overwrite the French set
        with English ones, which is worse than failing.
        """
        context = self.new_context(auth=True)
        page = context.new_page()
        try:
            page.goto(f"{self.base_url}/account/")
            select = page.locator("select[name$='preferred_language']").first
            if select.count() == 0:
                raise CaptureError(
                    "no preferred-language field on /account/ — the instance offers a "
                    "single admin language, so it cannot be captured in another")
            options = select.evaluate("el => Array.from(el.options).map(o => o.value)")
            if lang not in options:
                raise CaptureError(
                    f"the admin offers no '{lang}' language (has: {', '.join(o for o in options if o)})")
            select.select_option(lang)
            # requestSubmit, not a submit-button click: the account page carries
            # several panels and more than one button
            select.evaluate("el => el.form.requestSubmit()")
            page.wait_for_load_state("networkidle")
            chosen = page.locator("select[name$='preferred_language']").first.input_value()
            if chosen != lang:
                raise CaptureError(f"the admin language stayed '{chosen}' after asking for '{lang}'")
            self.storage_state = context.storage_state()
        finally:
            context.close()

    # -- one entry -----------------------------------------------------------------

    def output_path(self, name, lang, first_lang):
        suffix = "" if lang == first_lang else f".{lang}"
        return self.images_dir / f"{name}{suffix}.png"

    def capture(self, entry, lang, first_lang):
        context = self.new_context(auth=entry.get("auth", True))
        page = context.new_page()
        try:
            url = entry["url"]
            if not url.startswith("http"):
                url = self.base_url + url
            response = page.goto(url)
            if response is not None and response.status >= 400:
                raise CaptureError(f"HTTP {response.status} for {url}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(entry.get("wait", self.defaults.get("wait", 0)))

            for step in entry.get("setup") or []:
                self.run_step(page, step)

            page.evaluate("settle()")
            for callout in entry.get("callouts") or []:
                self.apply_callout(page, callout)

            out = self.output_path(entry["name"], lang, first_lang)
            out.parent.mkdir(parents=True, exist_ok=True)
            self.shoot(page, entry.get("capture") or {}, out)
            return out
        finally:
            context.close()

    def run_step(self, page, step):
        if not isinstance(step, dict) or len(step) != 1:
            raise CaptureError(f"a setup step must be a single-key mapping: {step}")
        (action, arg), = step.items()
        if action == "click":
            page.locator(arg).first.click()
        elif action == "hover":
            page.locator(arg).first.hover()
        elif action == "wait_for":
            page.wait_for_selector(arg, state="visible")
        elif action == "wait":
            page.wait_for_timeout(int(arg))
        elif action == "fill":
            page.locator(arg["selector"]).first.fill(str(arg["value"]))
        elif action == "select":
            page.locator(arg["selector"]).first.select_option(str(arg["value"]))
        elif action == "upload":
            page.locator(arg["selector"]).first.set_input_files(str(self.repo_dir / arg["path"]))
        elif action == "eval":
            page.evaluate(arg)
        else:
            raise CaptureError(f"unknown setup step '{action}'")

    def apply_callout(self, page, callout):
        if not isinstance(callout, dict) or len(callout) != 1:
            raise CaptureError(f"a callout must be a single-key mapping: {callout}")
        (kind, arg), = callout.items()
        if kind == "badge":
            target, n = arg["target"], int(arg["n"])
            self.require(page, target)
            page.evaluate("([s, n]) => badge(s, n)", [target, n])
        elif kind == "highlight":
            target = arg["target"] if isinstance(arg, dict) else arg
            self.require(page, target)
            page.evaluate("s => highlight(s)", target)
        else:
            raise CaptureError(f"unknown callout '{kind}' (badge or highlight)")

    @staticmethod
    def require(page, selector):
        if page.locator(selector).count() == 0:
            raise CaptureError(f"no element matches '{selector}'")

    def shoot(self, page, capture, out):
        selector = capture.get("selector")
        padding = capture.get("padding", self.defaults.get("padding", 0))
        if not selector:
            page.screenshot(path=str(out), full_page=capture.get("full_page", False))
            return
        target = page.locator(selector).first
        if target.count() == 0:
            raise CaptureError(f"no element matches capture selector '{selector}'")
        self.expand_viewport(page)
        box = target.bounding_box()
        if box is None:
            raise CaptureError(f"capture selector '{selector}' has no box (hidden?)")
        clip = {
            "x": max(box["x"] - padding, 0),
            "y": max(box["y"] - padding, 0),
            "width": box["width"] + 2 * padding,
            "height": box["height"] + 2 * padding,
        }
        page.screenshot(path=str(out), clip=clip)

    MAX_HEIGHT = 8000

    def expand_viewport(self, page):
        """The Wagtail admin scrolls inside <main>, not the document, so a
        full-page screenshot never sees below the fold. Grow the viewport to the
        tallest scroll container instead, so every crop is a plain viewport
        clip and no element is ever half-rendered."""
        w, h = self.defaults["viewport"]
        needed = page.evaluate("""() => {
            let max = document.documentElement.scrollHeight;
            for (const el of document.querySelectorAll('main, .w-content, [data-sidebar-content]')) {
                const r = el.getBoundingClientRect();
                max = Math.max(max, r.top + window.scrollY + el.scrollHeight);
            }
            return Math.ceil(max);
        }""")
        height = min(max(h, needed + 40), self.MAX_HEIGHT)
        if height != h:
            page.set_viewport_size({"width": w, "height": height})
            page.wait_for_timeout(200)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("manifest")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--repo-dir", default=".", help="repo the manifest belongs to (output root)")
    parser.add_argument("--images-dir", help="override the derived images directory")
    parser.add_argument("--lang", default="en", help="comma-separated; the first is the unsuffixed default")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="adl-docs-demo")
    parser.add_argument("--only", action="append", default=[], help="capture only these entry names")
    args = parser.parse_args()

    repo_dir = Path(args.repo_dir).resolve()
    defaults, entries = load_manifest(args.manifest)
    if args.only:
        entries = [e for e in entries if e["name"] in args.only]
    langs = [l.strip() for l in args.lang.split(",") if l.strip()]
    images_dir = images_dir_for(repo_dir, args.images_dir)

    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        runner = Runner(browser, args.base_url, defaults, repo_dir, images_dir, args.username, args.password)
        for lang in langs:
            if lang != langs[0]:
                print(f"== language {lang}")
                runner.set_language(lang)
            for entry in entries:
                try:
                    out = runner.capture(entry, lang, langs[0])
                    print(f"  ok   {entry['name']}  -> {out.relative_to(repo_dir) if out.is_relative_to(repo_dir) else out}")
                except (CaptureError, PlaywrightError) as e:
                    failures.append((entry["name"], lang, str(e).splitlines()[0]))
                    print(f"  FAIL {entry['name']} [{lang}]: {str(e).splitlines()[0]}")
        if len(langs) > 1:
            runner.set_language(langs[0])
        browser.close()

    print(f"{len(entries) * len(langs) - len(failures)} captured, {len(failures)} failed")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
