import {defineStore} from 'pinia'
import {fetchAvailabilitySummary} from '@/services/adlService'

export const useAvailabilityStore = defineStore('availability', {
    state: () => ({
        // Summary view state
        summaryData: null,
        stations: [],
        hourLabels: [], // Display labels (e.g., ["14:00", "15:00", ..., "13:00"])
        hourKeys: [],   // Full keys for data lookup (e.g., ["2025-05-31 14:00", ...])
        loadingSummary: false,

        // Detail view state
        detailData: null,
        loadingDetail: false,

        // Filters
        selectedConnectionId: null,
        connections: [],

        // Detail view params
        selectedStationLinkId: null,
        selectedYear: new Date().getFullYear(),
        selectedMonth: new Date().getMonth() + 1,

        error: null
    }),

    getters: {
        // Summary statistics
        totalStations: (state) => state.summaryData?.summary?.total_stations || 0,
        reportingStations: (state) => state.summaryData?.summary?.reporting || 0,
        stationsWithGaps: (state) => state.summaryData?.summary?.with_gaps || 0,
        offlineStations: (state) => state.summaryData?.summary?.offline || 0,

        // Connection info
        connectionName: (state) => state.summaryData?.connection?.name || '',
        isDaily: (state) => state.summaryData?.connection?.is_daily || false,

        // Time range
        timeRangeStart: (state) => state.summaryData?.time_range?.start || null,
        timeRangeEnd: (state) => state.summaryData?.time_range?.end || null,

        // Detail view getters
        detailStation: (state) => state.detailData?.station || null,
        detailConnection: (state) => state.detailData?.connection || null,
        detailPeriod: (state) => state.detailData?.period || null,
        availabilityMap: (state) => state.detailData?.availability || {},
        dailyCounts: (state) => state.detailData?.daily_counts || {},

        // Formatted display date for detail view
        displayMonth: (state) => {
            if (!state.selectedYear || !state.selectedMonth) return '...'
            const date = new Date(state.selectedYear, state.selectedMonth - 1)
            return date.toLocaleDateString(undefined, {month: 'long', year: 'numeric'})
        }
    },

    actions: {
        setSelectedConnection(connectionId) {
            this.selectedConnectionId = connectionId
            if (connectionId) {
                this.loadSummary()
            }
        },

        async loadSummary() {
            if (!this.selectedConnectionId) {
                this.stations = []
                this.summaryData = null
                this.hourLabels = []
                this.hourKeys = []
                return
            }

            this.loadingSummary = true
            this.error = null

            try {
                const response = await fetchAvailabilitySummary(
                    this.axios,
                    this.selectedConnectionId
                )

                this.summaryData = response.data
                this.stations = response.data.stations || []
                this.hourLabels = response.data.hour_labels || []
                this.hourKeys = response.data.hour_keys || []

            } catch (err) {
                console.error('Availability Summary Fetch Error:', err)
                this.error = err.message || 'Failed to load availability summary'
                this.summaryData = null
                this.stations = []
                this.hourLabels = []
                this.hourKeys = []
            } finally {
                this.loadingSummary = false
            }
        },

        async loadDetail(stationLinkId, year = null, month = null) {
            this.selectedStationLinkId = stationLinkId

            if (year) this.selectedYear = year
            if (month) this.selectedMonth = month

            this.loadingDetail = true
            this.error = null

            try {
                // const response = await fetchAvailabilityDetail(
                //     this.axios,
                //     stationLinkId,
                //     this.selectedYear,
                //     this.selectedMonth
                // )

                this.detailData = [] // response.data

            } catch (err) {
                console.error('Availability Detail Fetch Error:', err)
                this.error = err.message || 'Failed to load availability detail'
                this.detailData = null
            } finally {
                this.loadingDetail = false
            }
        },

        setDetailMonth(date) {
            if (date) {
                this.selectedYear = date.getFullYear()
                this.selectedMonth = date.getMonth() + 1

                if (this.selectedStationLinkId) {
                    this.loadDetail(this.selectedStationLinkId)
                }
            }
        },

        // Navigate to previous/next month in detail view
        previousMonth() {
            if (this.selectedMonth === 1) {
                this.selectedMonth = 12
                this.selectedYear -= 1
            } else {
                this.selectedMonth -= 1
            }

            if (this.selectedStationLinkId) {
                this.loadDetail(this.selectedStationLinkId)
            }
        },

        nextMonth() {
            if (this.selectedMonth === 12) {
                this.selectedMonth = 1
                this.selectedYear += 1
            } else {
                this.selectedMonth += 1
            }

            if (this.selectedStationLinkId) {
                this.loadDetail(this.selectedStationLinkId)
            }
        },

        // Helper to get cell status for a station at a specific hour key
        getCellStatus(station, hourKey) {
            const count = station.hourly_counts?.[hourKey] || 0
            const expected = station.expected_hourly || 1

            if (count === 0) return 'empty'

            const ratio = count / expected
            if (ratio >= 0.9) return 'full'
            if (ratio >= 0.5) return 'partial'
            return 'low'
        },

        // Helper to get record count for a station at a specific hour key
        getHourlyCount(station, hourKey) {
            return station.hourly_counts?.[hourKey] || 0
        },

        // Helper to get status label
        getStatusLabel(status) {
            const labels = {
                'complete': 'Complete',
                'gaps': 'Has Gaps',
                'critical': 'Critical',
                'offline': 'Offline'
            }
            return labels[status] || status
        },

        // Helper to get status severity for PrimeVue components
        getStatusSeverity(status) {
            const severities = {
                'complete': 'success',
                'gaps': 'warn',
                'critical': 'danger',
                'offline': 'secondary'
            }
            return severities[status] || 'info'
        }
    }
})