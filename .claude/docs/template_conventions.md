# Template Conventions (Django/Wagtail HTML)

Conventions for all HTML templates in ADL. Referenced from `CLAUDE.md`.

## General rules

- **No inline styles** — never use `style="..."` attributes. Extract all CSS into a
  `{% block extra_css %}<style>…</style>{% endblock %}` block and give elements semantic class names.
  When the same vocabulary is needed on more than one page (status badges, pills), escalate to a
  shared stylesheet loaded by an `insert_global_admin_css` hook rather than copying the block.
- **Multi-line comments use `{% comment %}`** — the `{# … #}` syntax is for single-line comments only.
  When a comment spans multiple lines, always use a `{% comment %}…{% endcomment %}` block:

  ```django
  {% comment %}
      Always rendered, whatever the ladder concluded — nothing else
      reports which broker stack an installation runs.
  {% endcomment %}
  ```
- **Modern JS** — use `const` and `let`; never `var`.
- **JS placement** — all JavaScript goes in `{% block extra_js %}…{% endblock %}` at the bottom of the template. Wrap
  code in `document.addEventListener('DOMContentLoaded', function () { … })` instead of IIFEs `(function(){ … }())`.

## Admin pages: extend `wagtailadmin/generic/base.html`

Every function-based-view admin page extends **`wagtailadmin/generic/base.html`** — never
`wagtailadmin/base.html` with a manual header include. The generic base renders Wagtail's slim header
(breadcrumbs + screen-reader-only `h1`) automatically when `breadcrumbs_items` is in the context.

Do **not** include `wagtailadmin/shared/header.html` yourself: that template silently ignores a
`breadcrumbs` variable (it has a fixed list of accepted variables), which is exactly the bug this
pattern replaced.

**One legitimate exception:** `config/templates/wagtailadmin/base.html` extends `wagtailadmin/base.html`
because it *is* ADL's override of Wagtail's base — it overrides `{% block branding_logo %}` to inject the
ADL logo and version. That file is infrastructure, not a page. No page template should follow it.

### Template contract

```django
{% extends "wagtailadmin/generic/base.html" %}
{% load i18n wagtailadmin_tags %}

{% block titletag %}…{% endblock %}

{% block extra_css %}
    {{ block.super }}
    <style>…</style>
{% endblock %}

{% block main_content %}
    …page body…
{% endblock %}
```

- Body goes in `{% block main_content %}` — the base already wraps it in `<div class="nice-padding">`,
  so never add your own `nice-padding` wrapper.
- **Top breathing space belongs in a global hook, not the page.** ADL does not yet have an
  `insert_global_admin_css` hook, so existing pages hack it per-page — `dispatch_channel_locks.html`
  opens with `<div style="margin-top: 40px">`. When the hook is added to `core/wagtail_hooks.py`, it
  should apply `margin-top: 2rem` (the `w-mt-8` value Wagtail's own pages use) to the slim-header +
  bare-`nice-padding` pairing, and those per-page hacks come out. Don't add new ones.

### View context contract

```python
context = {
    "breadcrumbs_items": [
        {"url": reverse("wagtailadmin_home"), "label": _("Home")},
        {"url": reverse("connections_list"), "label": _("Connections")},
        {"url": None, "label": current_page_label},  # leaf: url=None, NOT ""
    ],
    "header_title": …,  # slim header's sr-only h1 + titletag fallback
"header_icon": "cogs",  # icon shown beside the breadcrumbs
...
}
```

- **Leaf crumb uses `url: None`** — the breadcrumbs component checks `is not None`, so an empty
  string renders a useless self-link.
- `header_title` should carry what a big header would have shown: combine title and subtitle
  sensibly, e.g. `_("Dispatch Locks — %s") % channel.name`.
- Without `breadcrumbs_items` in context the base falls back to the old big header
  (`page_title`/`page_subtitle`) — always provide a trail instead.

### What the slim header cannot do

- **No visible page title** — the page identity is carried by the leaf breadcrumb. If the old
  header's subtitle carried real information, fold it into the leaf crumb label
  (e.g. `"Step 2 of 3 — Feed Details"`) or add a lead line at the top of `main_content`.
- **No action buttons** — `action_url`/`action_text` don't exist here. Put action bars
  (e.g. "New config", "Edit Details") at the top of `main_content` using the
  `button bicolor button--icon` idiom.

Reference examples: `core/templates/core/dispatch_channel_locks.html` + its view
`core/views.py:dispatch_channel_locks` (breadcrumbs built in the view, `<table class="listing">`,
`help-block help-info` callouts, POST-form actions), and `core/templates/core/connection_list.html`.

## CSS variables

ADL has **one** CSS token context, and one place that deliberately isn't CSS at all:

| Context                                                                  | Variables                          | Where defined        |
|--------------------------------------------------------------------------|------------------------------------|----------------------|
| **Wagtail admin** templates (`extends "wagtailadmin/generic/base.html"`) | `--w-color-*`                      | Wagtail 7 admin CSS  |
| **Vue components** (`monitoring/monitoring-ui-vue/`, `viewer/`)          | PrimeVue theme + SFC-scoped styles | the component itself |

Vue components are mounted into admin pages but style themselves through PrimeVue and scoped SFC
styles. Don't reach for `--w-color-*` inside a `.vue` file, and don't invent a second token
namespace for ADL — there is no project-branded token set, and adding one would need a real reason.

**Wagtail 7 removed the old unprefixed `--color-*` aliases entirely — use `--w-color-*` only.**
`core/templates/adl/load_stations_oscar.html` still uses `var(--color-border, …)`,
`var(--color-positive, …)` and friends; those resolve to nothing and silently render their hardcoded
hex fallbacks. Fix on sight.

Key `--w-color-*` tokens for admin templates:

- Borders: `--w-color-border-furniture`
- Muted text / secondary: `--w-color-grey-400`, `--w-color-text-meta`
- Subtle backgrounds / panel header backgrounds: `--w-color-grey-50`, `--w-color-grey-100`
- Menus: `--w-color-surface-menus`, `--w-color-surface-field`, `--w-color-surface-page`
- Labels / primary text: `--w-color-text-label`
- White: `--w-color-white`
- Status colours: `--w-color-info-100`, `--w-color-positive-100`, `--w-color-warning-100`, `--w-color-critical-200`
- Brand/action colours: `--w-color-primary`, `--w-color-secondary`

Using the tokens rather than hexes is what makes a page follow Wagtail's dark mode instead of
drifting from it.

## Known debt

These predate the conventions and are recorded so they read as debt, not precedent:

- **Inline `style="` attributes** survive in roughly 20 templates — worst are
  `core/templates/core/dispatch_channel_station_links.html` (17) and
  `core/templates/core/dispatch_channel_locks.html` (7), where the status pills are inline-styled
  hexes (`#1f7d51` / `#d9303e` / `#666`).
- **Three incompatible status-badge conventions** coexist: BEM `.status-badge` with copy-pasted CSS
  (`core/templates/core/panels/sl_collection_status.html`), the inline-styled pills above, and
  Wagtail CSS vars + icons (`monitoring/templates/monitoring/network_monitoring.html`). Wagtail's own
  `{% status %}` / `w-status` component is used nowhere. New pages should use the shared stylesheet;
  retrofitting the three is a separate piece of work.
- **No `insert_global_admin_css` hook exists yet**, so there is nowhere for shared admin CSS to live.
  Adding it is the prerequisite for both bullets above.
