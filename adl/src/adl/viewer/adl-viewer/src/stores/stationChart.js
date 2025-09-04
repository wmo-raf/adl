// stores/stationChart.js
import {defineStore} from 'pinia'
import {v4 as uuidv4} from 'uuid'

import {fetchStationLinkDetail, fetchStationLinkTimeseriesData} from '@/services/adlService'

import {useNetworkStore} from "@/stores/network.js";

export const useStationChartStore = defineStore('stationChart', {
    state: () => ({
        charts: {}
    }),

    actions: {
        addChart() {
            const id = uuidv4()
            this.charts[id] = {
                id,
                connectionId: null,
                stationId: null,
                stationDetail: null,
                startDate: null,
                endDate: null,
                dataParameterId: null,
                timeseriesData: null,
                loading: false,
                error: null,
            }
            return id
        },
        removeChart(id) {
            delete this.charts[id]
        },
        updateChartConfig(id, config) {
            if (this.charts[id]) {
                Object.assign(this.charts[id], config)
            }
        },
        async loadConnectionStations(connectionId) {
            const networkStore = useNetworkStore()

            await networkStore.loadNetworkConnectionStations(connectionId)
        },
        async loadStationDetail(chartId, stationId) {
            const response = await fetchStationLinkDetail(this.axios, stationId)
            const {data} = response

            const chart = this.charts[chartId]
            if (!chart) return

            const {data_dates} = data

            chart.stationDetail = data

            if (data_dates.earliest_time && data_dates.latest_time) {
                const {earliest_time, latest_time} = data_dates

                const end = new Date(latest_time)

                // Default to 1 day before the end date, or the earliest date if less than 1 day of data
                let start = new Date(end)
                start.setDate(end.getDate() - 1)

                if (start < new Date(earliest_time)) {
                    start = new Date(earliest_time)
                }
                chart.startDate = start
                chart.endDate = end
            }


        },
        async loadChartData(id) {
            const chart = this.charts[id]

            if (!chart || !chart.stationId || !chart.dataParameterId) return


            chart.loading = true
            chart.error = null

            const startDate = chart.startDate
            const endDate = chart.endDate

            if (!startDate || !endDate) {
                chart.error = "Start date and end date must be set"
                chart.loading = false
                return
            }

            try {
                const response = await fetchStationLinkTimeseriesData(this.axios, chart.stationId, {
                    startDate,
                    endDate,
                    paginate: 'false'
                })
                const {data} = response
                chart.timeseriesData = data.results
            } catch (err) {
                chart.error = err.message
                chart.timeseriesData = null
            } finally {
                chart.loading = false
            }
        }
    }
})
