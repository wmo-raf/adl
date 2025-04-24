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

            chart.stationDetail = data

        },
        async loadChartData(id) {
            const chart = this.charts[id]

            if (!chart || !chart.stationId || !chart.dataParameterId) return

            chart.loading = true
            chart.error = null

            try {
                const response = await fetchStationLinkTimeseriesData(this.axios, chart.stationId, 1)
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
