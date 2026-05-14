import {defineStore} from "pinia"
import {fetchStationLinkLatestData} from "@/services/adlService.js"

export const useWidgetStore = defineStore('widget', {
    state: () => ({
        stations: [],
        parameters: [],
        latestData: {},
        currentIndex: 0,
        activeView: 'rotating',
        lastPolledAt: null,
        loading: false,
    }),

    getters: {
        currentStation: (state) => state.stations[state.currentIndex] || null,
        stationCount: (state) => state.stations.length,
        currentStationData: (state) => {
            const station = state.stations[state.currentIndex]
            if (!station) return []
            return state.latestData[station.id] || []
        },
    },

    actions: {
        init(stations, parameters, defaultView) {
            this.stations = stations
            this.parameters = parameters
            this.activeView = defaultView
        },

        async pollAllStations() {
            this.loading = true
            try {
                for (const station of this.stations) {
                    const res = await fetchStationLinkLatestData(this.axios, station.id)
                    this.latestData[station.id] = res.data.data || []
                }
                this.lastPolledAt = new Date()
            } catch (e) {
                console.error('Widget poll error:', e)
            } finally {
                this.loading = false
            }
        },

        startPolling(intervalMinutes) {
            this.pollAllStations()
            setInterval(() => this.pollAllStations(), intervalMinutes * 60 * 1000)
        },

        nextStation() {
            if (this.stations.length > 0) {
                this.currentIndex = (this.currentIndex + 1) % this.stations.length
            }
        },

        prevStation() {
            if (this.stations.length > 0) {
                this.currentIndex = (this.currentIndex - 1 + this.stations.length) % this.stations.length
            }
        },

        goToStation(index) {
            if (index >= 0 && index < this.stations.length) {
                this.currentIndex = index
            }
        },

        setView(view) {
            this.activeView = view
        },
    }
})
