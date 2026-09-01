import {nextTick, reactive, ref, watch} from 'vue'
import {format as dateFormat} from 'date-fns'

import {useNetworkStore} from '@/stores/network.js'
import {useStationStore} from '@/stores/station.js'
import {useStationTimeseriesDataStore} from '@/stores/stationTimeseriesData.js'
import {fetchStationLinkDetail} from '@/services/adlService.js'

// Query params owned by the table view. Any other param present in the URL
// (including future `chart`) is preserved untouched by write-back.
export const TABLE_URL_PARAMS = ['connection', 'station', 'category', 'from', 'to']

// CHART URL SCHEME (design only — not implemented yet):
//   chart=<connectionId>:<stationLinkId>:<parameterId>:<from>:<to>   (repeatable, one per panel)
// Empty segments mean "use the default"; dates are YYYY-MM-DD local.
//   e.g. ?chart=3:42:17:2026-01-01:&chart=3:55:17::

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/
const SEED_TIMEOUT_MS = 15000

// --- module-scope singleton state (shared by TableView and TimeSeriesDataTable) ---
const warnings = ref([])
const warningsDismissed = ref(false)
const isSeeding = ref(false)
// reactive so waitFor() can watch for the pending filters being consumed
const pending = reactive({station: null, connection: null, category: null, from: null, to: null})

let writeBackStarted = false

// The "last 1 day of available data" default, extracted from the
// TimeSeriesDataTable station-detail watcher so URL write-back can compare
// against the same values the table would pick on its own.
export function computeDefaultDateRange(dataDates) {
    if (!dataDates) {
        return null
    }
    const {latest_time, earliest_time} = dataDates
    if (!latest_time || !earliest_time) {
        return null
    }

    const end = new Date(latest_time)

    // Default to 1 day before the end date, or the earliest date if less than 1 day of data
    let start = new Date(end)
    start.setDate(end.getDate() - 1)

    if (start < new Date(earliest_time)) {
        start = new Date(earliest_time)
    }

    return {start, end}
}

function warn(message) {
    warnings.value.push(message)
}

function parseLocalDate(value) {
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
function waitFor(predicate, timeoutMs = SEED_TIMEOUT_MS) {
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

function parseUrl() {
    const params = new URLSearchParams(window.location.search)
    let any = false

    for (const key of ['connection', 'station']) {
        const raw = params.get(key)
        if (raw === null || raw === '') continue
        any = true
        const id = parseInt(raw, 10)
        if (Number.isNaN(id)) {
            warn(`Invalid ${key} id '${raw}' in the link was ignored.`)
        } else {
            pending[key] = id
        }
    }

    for (const key of ['category', 'from', 'to']) {
        const raw = params.get(key)
        if (raw === null || raw === '') continue
        any = true
        pending[key] = raw
    }

    return any
}

// Called by the TimeSeriesDataTable station-detail watcher, in the same tick
// where the default dates are computed — one-shot, so later station changes
// fall back to plain default behavior.
function consumePendingDates(dataDates) {
    if (pending.from === null && pending.to === null) {
        return null
    }
    const from = pending.from
    const to = pending.to
    pending.from = null
    pending.to = null

    const defaults = computeDefaultDateRange(dataDates)
    if (!defaults) {
        return null
    }

    let fromDate = null
    let toDate = null

    if (from !== null) {
        fromDate = parseLocalDate(from)
        if (!fromDate) {
            warn(`Invalid start date '${from}' in the link was ignored.`)
        }
    }
    if (to !== null) {
        toDate = parseLocalDate(to)
        if (!toDate) {
            warn(`Invalid end date '${to}' in the link was ignored.`)
        }
    }

    if (!fromDate && !toDate) {
        return null
    }

    const earliest = new Date(dataDates.earliest_time)
    const latest = new Date(dataDates.latest_time)

    // Treat the requested end date as inclusive (end of that day) when
    // checking whether the whole range misses the archive.
    if (toDate) {
        const toEndOfDay = new Date(toDate)
        toEndOfDay.setHours(23, 59, 59, 999)
        if (toEndOfDay < earliest) {
            warn(
                `Requested date range is outside the available data ` +
                `(${dateFormat(earliest, 'yyyy-MM-dd')} to ${dateFormat(latest, 'yyyy-MM-dd')}); showing the default range.`
            )
            return null
        }
    }
    if (fromDate && fromDate > latest) {
        warn(
            `Requested date range is outside the available data ` +
            `(${dateFormat(earliest, 'yyyy-MM-dd')} to ${dateFormat(latest, 'yyyy-MM-dd')}); showing the default range.`
        )
        return null
    }

    // Silent clamp to the archive edges (matches the date pickers' min/max)
    let start = fromDate || defaults.start
    let end = toDate || defaults.end
    if (start < earliest) {
        start = new Date(earliest)
    }
    if (end > latest) {
        end = new Date(latest)
    }

    if (start > end) {
        warn(`Start date '${from}' is after end date '${to}'; showing the default range.`)
        return null
    }

    return {start, end}
}

// Called by the TimeSeriesDataTable categories watcher — one-shot.
function consumePendingCategory(categories) {
    if (pending.category === null) {
        return null
    }
    const requested = pending.category
    pending.category = null

    if (categories && categories.some((category) => category.id === requested)) {
        return requested
    }
    warn(`Data category '${requested}' is not available for this station.`)
    return null
}

function syncUrl(networkStore, stationStore, timeseriesStore) {
    const params = new URLSearchParams(window.location.search)
    for (const key of TABLE_URL_PARAMS) {
        params.delete(key)
    }

    const stationId = stationStore.selectedStationId
    const connectionId = networkStore.selectedNetworkConnection

    if (stationId) {
        params.set('station', String(stationId))
    } else if (connectionId && networkStore.networkConnections.length > 1) {
        // With a station set the connection is derivable; with a single
        // connection it is the default — omitted in both cases.
        params.set('connection', String(connectionId))
    }

    if (stationId) {
        const categoryId = timeseriesStore.selectedDataCategoryId
        const defaultCategoryId = stationStore.selectedStationDataCategories[0]?.id
        if (categoryId && categoryId !== defaultCategoryId) {
            params.set('category', String(categoryId))
        }

        const defaults = computeDefaultDateRange(stationStore.selectedStationLinkDetail?.data_dates)
        if (defaults) {
            const from = timeseriesStore.startDate ? dateFormat(timeseriesStore.startDate, 'yyyy-MM-dd') : null
            const to = timeseriesStore.endDate ? dateFormat(timeseriesStore.endDate, 'yyyy-MM-dd') : null
            if (from && from !== dateFormat(defaults.start, 'yyyy-MM-dd')) {
                params.set('from', from)
            }
            if (to && to !== dateFormat(defaults.end, 'yyyy-MM-dd')) {
                params.set('to', to)
            }
        }
    }

    const qs = params.toString()
    const url = window.location.pathname + (qs ? `?${qs}` : '') + window.location.hash
    window.history.replaceState(null, '', url)
}

function startWriteBack(networkStore, stationStore, timeseriesStore) {
    if (writeBackStarted) {
        return
    }
    writeBackStarted = true

    watch(() => ({
        connection: networkStore.selectedNetworkConnection,
        station: stationStore.selectedStationId,
        category: timeseriesStore.selectedDataCategoryId,
        from: timeseriesStore.startDate ? dateFormat(timeseriesStore.startDate, 'yyyy-MM-dd') : null,
        to: timeseriesStore.endDate ? dateFormat(timeseriesStore.endDate, 'yyyy-MM-dd') : null,
        // detail load changes what counts as "default", so re-sync on it too
        detailLoaded: !!stationStore.selectedStationLinkDetail,
    }), () => syncUrl(networkStore, stationStore, timeseriesStore), {immediate: true})
}

async function initFromUrl() {
    const networkStore = useNetworkStore()
    const stationStore = useStationStore()
    const timeseriesStore = useStationTimeseriesDataStore()

    const hasParams = parseUrl()
    if (!hasParams) {
        startWriteBack(networkStore, stationStore, timeseriesStore)
        return
    }

    isSeeding.value = true

    const connectionsLoaded = await waitFor(() => networkStore.networkConnections.length > 0)
    if (!connectionsLoaded) {
        isSeeding.value = false
        startWriteBack(networkStore, stationStore, timeseriesStore)
        return
    }

    let stationSelected = false

    if (pending.station !== null) {
        // Probe the station link directly (NOT through the station store):
        // populating the store's detail here would fire the table's
        // detail watcher twice — once with this probe, once with the
        // cascade's own re-fetch — and the second firing would reset the
        // one-shot URL dates back to defaults.
        let probedDetail = null
        try {
            const response = await fetchStationLinkDetail(networkStore.axios, pending.station)
            probedDetail = response.data
        } catch (err) {
            probedDetail = null
        }

        if (!probedDetail) {
            warn(`Station link ${pending.station} was not found; showing defaults.`)
            pending.station = null
        } else {
            const trueConnection = probedDetail.network_connection

            if (pending.connection !== null && pending.connection !== trueConnection) {
                warn(`Connection ${pending.connection} does not match station ${pending.station}; corrected to ${trueConnection}.`)
            }

            if (!networkStore.getNetworkConnectionById(trueConnection)) {
                warn(`Station link ${pending.station} was not found; showing defaults.`)
                pending.station = null
            } else {
                const stationId = pending.station
                pending.station = null

                // Setting the connection triggers StationSelect's watcher
                // (clears any stale station state) and the connection
                // select's watcher (loads the station list).
                networkStore.selectedNetworkConnection = trueConnection
                await waitFor(() => networkStore.getNetworkConnectionStations(trueConnection).length > 0)
                await nextTick()
                stationStore.selectStation(stationId)
                stationSelected = true
            }
        }
    }

    if (!stationSelected && pending.connection !== null) {
        if (networkStore.getNetworkConnectionById(pending.connection)) {
            networkStore.selectedNetworkConnection = pending.connection
        } else {
            warn(`Connection ${pending.connection} was not found.`)
        }
    }
    pending.connection = null

    if (stationSelected) {
        // category/dates are consumed by the TimeSeriesDataTable watchers once
        // the station detail lands; nulled on consumption
        await waitFor(() => pending.category === null && pending.from === null && pending.to === null)
    } else if (pending.category !== null || pending.from !== null || pending.to !== null) {
        warn('Category and date filters in the link were ignored because no station is selected.')
    }
    pending.category = null
    pending.from = null
    pending.to = null

    isSeeding.value = false
    startWriteBack(networkStore, stationStore, timeseriesStore)
}

function dismissWarnings() {
    warningsDismissed.value = true
}

export function useTableUrlState() {
    return {
        warnings,
        warningsDismissed,
        isSeeding,
        dismissWarnings,
        initFromUrl,
        consumePendingDates,
        consumePendingCategory,
    }
}
