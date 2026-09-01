import {ref, watch} from 'vue'
import {format as dateFormat} from 'date-fns'

import {useNetworkStore} from '@/stores/network.js'
import {useStationChartStore} from '@/stores/stationChart.js'
import {computeDefaultDateRange} from './useTableUrlState.js'
import {
    dismissWarnings,
    parseLocalDate,
    replaceUrlParams,
    waitFor,
    warn,
    warnings,
    warningsDismissed,
} from './urlStateShared.js'

// CHART URL SCHEME — one repeatable packed param per chart panel:
//   chart=<connectionId>:<stationLinkId>:<parameterId>:<from>:<to>
// Empty segments mean "use the default"; dates are YYYY-MM-DD local.
//   e.g. ?chart=3:42:17:2026-01-01:&chart=3:55:17::
// On write-back the connection segment is omitted when a station is set
// (derivable from the station link) and date segments are omitted when
// they equal the default "last 1 day of available data" range.
export const CHART_URL_PARAM = 'chart'

const isSeeding = ref(false)
let writeBackStarted = false

function parseIntSegment(raw, label, specText) {
    if (!raw) {
        return null
    }
    const id = parseInt(raw, 10)
    if (Number.isNaN(id)) {
        warn(`Invalid ${label} '${raw}' in chart link '${specText}' was ignored.`)
        return null
    }
    return id
}

function parseChartSpecs() {
    const params = new URLSearchParams(window.location.search)
    const specs = []
    for (const specText of params.getAll(CHART_URL_PARAM)) {
        const segments = specText.split(':')
        specs.push({
            specText,
            connection: parseIntSegment(segments[0], 'connection id', specText),
            station: parseIntSegment(segments[1], 'station id', specText),
            parameter: parseIntSegment(segments[2], 'parameter id', specText),
            from: segments[3] || null,
            to: segments[4] || null,
        })
    }
    return specs
}

// Applies URL dates onto a seeded chart, over the defaults set by
// loadStationDetail. Whole range outside the archive → warn, keep defaults;
// edges silently clamp; start > end after clamping → warn, keep defaults.
function applyUrlDates(chart, spec) {
    if (spec.from === null && spec.to === null) {
        return
    }
    const dataDates = chart.stationDetail?.data_dates
    if (!dataDates?.earliest_time || !dataDates?.latest_time) {
        return
    }

    let fromDate = null
    let toDate = null
    if (spec.from !== null) {
        fromDate = parseLocalDate(spec.from)
        if (!fromDate) {
            warn(`Invalid start date '${spec.from}' in chart link '${spec.specText}' was ignored.`)
        }
    }
    if (spec.to !== null) {
        toDate = parseLocalDate(spec.to)
        if (!toDate) {
            warn(`Invalid end date '${spec.to}' in chart link '${spec.specText}' was ignored.`)
        }
    }
    if (!fromDate && !toDate) {
        return
    }

    const earliest = new Date(dataDates.earliest_time)
    const latest = new Date(dataDates.latest_time)
    const range = `${dateFormat(earliest, 'yyyy-MM-dd')} to ${dateFormat(latest, 'yyyy-MM-dd')}`

    if (toDate) {
        const toEndOfDay = new Date(toDate)
        toEndOfDay.setHours(23, 59, 59, 999)
        if (toEndOfDay < earliest) {
            warn(`Chart date range is outside the available data (${range}); showing the default range.`)
            return
        }
        toDate = toEndOfDay
    }
    if (fromDate && fromDate > latest) {
        warn(`Chart date range is outside the available data (${range}); showing the default range.`)
        return
    }

    let start = fromDate || chart.startDate
    let end = toDate || chart.endDate
    if (start < earliest) {
        start = new Date(earliest)
    }
    if (end > latest) {
        end = new Date(latest)
    }
    if (start > end) {
        warn(`Chart start date '${spec.from}' is after end date '${spec.to}'; showing the default range.`)
        return
    }

    chart.startDate = start
    chart.endDate = end
}

async function seedChart(chartStore, networkStore, spec) {
    if (spec.station === null && spec.connection === null) {
        warn(`Chart link '${spec.specText}' was ignored (no station or connection).`)
        return
    }

    const id = chartStore.addChart()
    const chart = chartStore.charts[id]

    if (spec.station === null) {
        // Connection-only panel: preselect the connection, nothing to plot yet
        if (networkStore.getNetworkConnectionById(spec.connection)) {
            chart.connectionId = spec.connection
            await chartStore.loadConnectionStations(spec.connection)
        } else {
            warn(`Chart connection ${spec.connection} was not found; panel removed.`)
            chartStore.removeChart(id)
        }
        return
    }

    // loadStationDetail sets stationDetail plus the default date range
    try {
        await chartStore.loadStationDetail(id, spec.station)
    } catch (err) {
        chart.stationDetail = null
    }
    if (!chart.stationDetail) {
        warn(`Chart station link ${spec.station} was not found; panel removed.`)
        chartStore.removeChart(id)
        return
    }

    const trueConnection = chart.stationDetail.network_connection
    if (spec.connection !== null && spec.connection !== trueConnection) {
        warn(`Chart connection ${spec.connection} does not match station ${spec.station}; corrected to ${trueConnection}.`)
    }
    if (!networkStore.getNetworkConnectionById(trueConnection)) {
        warn(`Chart station link ${spec.station} was not found; panel removed.`)
        chartStore.removeChart(id)
        return
    }

    chart.connectionId = trueConnection
    chart.stationId = spec.station
    await chartStore.loadConnectionStations(trueConnection)

    applyUrlDates(chart, spec)

    if (spec.parameter !== null) {
        const parameters = chart.stationDetail.data_parameters || []
        if (parameters.some((parameter) => parameter.id === spec.parameter)) {
            chart.dataParameterId = spec.parameter
            await chartStore.loadChartData(id)
        } else {
            warn(`Chart parameter ${spec.parameter} is not available for station ${spec.station}.`)
        }
    }
}

function serializeChart(chart) {
    if (!chart.connectionId && !chart.stationId) {
        return null
    }

    // connection is derivable when a station is set — omit it then
    const connection = chart.stationId ? '' : String(chart.connectionId)
    const station = chart.stationId ? String(chart.stationId) : ''
    const parameter = chart.dataParameterId ? String(chart.dataParameterId) : ''

    let from = ''
    let to = ''
    const defaults = computeDefaultDateRange(chart.stationDetail?.data_dates)
    if (defaults) {
        const fromValue = chart.startDate ? dateFormat(chart.startDate, 'yyyy-MM-dd') : null
        const toValue = chart.endDate ? dateFormat(chart.endDate, 'yyyy-MM-dd') : null
        if (fromValue && fromValue !== dateFormat(defaults.start, 'yyyy-MM-dd')) {
            from = fromValue
        }
        if (toValue && toValue !== dateFormat(defaults.end, 'yyyy-MM-dd')) {
            to = toValue
        }
    }

    return [connection, station, parameter, from, to].join(':')
}

function syncUrl(chartStore) {
    const params = new URLSearchParams(window.location.search)
    params.delete(CHART_URL_PARAM)

    for (const chart of Object.values(chartStore.charts)) {
        const spec = serializeChart(chart)
        if (spec !== null) {
            params.append(CHART_URL_PARAM, spec)
        }
    }

    replaceUrlParams(params)
}

function startWriteBack(chartStore) {
    if (writeBackStarted) {
        return
    }
    writeBackStarted = true

    watch(() => chartStore.charts, () => syncUrl(chartStore), {deep: true, immediate: true})
}

async function initFromUrl() {
    const networkStore = useNetworkStore()
    const chartStore = useStationChartStore()

    const specs = parseChartSpecs()
    if (!specs.length) {
        startWriteBack(chartStore)
        return
    }

    isSeeding.value = true

    const connectionsLoaded = await waitFor(() => networkStore.networkConnections.length > 0)
    if (connectionsLoaded) {
        for (const spec of specs) {
            await seedChart(chartStore, networkStore, spec)
        }
    }

    isSeeding.value = false
    startWriteBack(chartStore)
}

export function useChartUrlState() {
    return {
        warnings,
        warningsDismissed,
        isSeeding,
        dismissWarnings,
        initFromUrl,
    }
}
