// Single entry point for maplibre-gl in the viewer.
//
// maplibre-gl 6 is ESM-only and locates its worker at runtime via
// `new URL(<computed name>, import.meta.url)`, which Vite cannot see, so the
// worker file is never emitted and maps fail with a 404 for
// maplibre-gl-worker.mjs. Vite's `?worker&url` import makes Vite bundle the
// worker and hand back its URL, which we register once here.
// See https://maplibre.org/maplibre-gl-js/docs/#installation (Vite).
import * as maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'

// In local dev the page is served by Django (e.g. :8004) while Vite serves
// the worker from its dev server (e.g. :5174). Browsers refuse to start a
// worker from another origin, so wrap it in a same-origin blob: module worker
// that imports the real one (the same trick maplibre uses for CDN loads).
// Production bundles live under /static/vue/ on the page's own origin, so
// this branch never runs there.
// Vite returns a root-relative path ("/static/vue/..."), so resolve it against
// this module's own URL (the Vite server in dev, the page origin in a build),
// not against the page.
function resolveWorkerUrl(url) {
    const absolute = new URL(url, import.meta.url)
    if (absolute.origin === window.location.origin) {
        return url
    }
    const shim = new Blob([`import ${JSON.stringify(absolute.href)};`], {type: 'text/javascript'})
    return URL.createObjectURL(shim)
}

maplibregl.setWorkerUrl(resolveWorkerUrl(workerUrl))

export default maplibregl
