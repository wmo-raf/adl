import {ref, watch} from 'vue'

// Shared plumbing for the per-page URL-state composables
// (useTableUrlState, useChartUrlState). Each viewer page is its own
// mini-app, so this module-scope state is page-local at runtime.

export const DATE_RE = /^\d{4}-\d{2}-\d{2}$/
export const SEED_TIMEOUT_MS = 15000

// Warnings accumulated while seeding state from the URL, surfaced as one
// dismissible banner. Only the seeding phase pushes here, so later filter
// changes can never resurrect the banner.
export const warnings = ref([])
export const warningsDismissed = ref(false)

export function warn(message) {
    warnings.value.push(message)
}

export function dismissWarnings() {
    warningsDismissed.value = true
}

export function parseLocalDate(value) {
    if (!DATE_RE.test(value)) {
        return null
    }
    const [year, month, day] = value.split('-').map(Number)
    const date = new Date(year, month - 1, day)
    // Reject impossible dates like 2026-02-31, which Date() silently rolls over
    if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
        return null
    }
    return date
}

// Resolves when predicate() is truthy, or with false after timeoutMs.
export function waitFor(predicate, timeoutMs = SEED_TIMEOUT_MS) {
    return new Promise((resolve) => {
        if (predicate()) {
            resolve(true)
            return
        }

        const timer = setTimeout(() => {
            stop()
            resolve(false)
        }, timeoutMs)

        // no `immediate` — the callback can only run after watch() returns,
        // so `stop` is always assigned by the time it is called
        const stop = watch(predicate, (value) => {
            if (value) {
                clearTimeout(timer)
                stop()
                resolve(true)
            }
        })
    })
}

// Replaces the current URL (history.replaceState, never pushState) with the
// given URLSearchParams, preserving path and hash.
export function replaceUrlParams(params) {
    const qs = params.toString()
    const url = window.location.pathname + (qs ? `?${qs}` : '') + window.location.hash
    window.history.replaceState(null, '', url)
}
