import {defineStore} from 'pinia'
import {keyBy} from "lodash";

import {
    fetchDataParameters,
    fetchNetworkConnections,
    fetchNetworkConnectionStations,
    fetchStationLinkLatestData
} from '@/services/adlService'

export const useTableViewStore = defineStore('tableView', {
    state: () => ({
        dataParameters: {},
        networkConnections: [],
        selectedNetworkConnection: null,
        networkConnectionStations: {},
        selectedStation: null,
        selectedStationLatestData: null,
        loading: false,
        error: null
    }),
    actions: {
        async loadDataParameters() {
            this.loading = true
            this.error = null
            try {
                const response = await fetchDataParameters(this.axios)
                this.dataParameters = keyBy(response.data, "id")
            } catch (err) {
                this.error = err.message || 'Failed to fetch data parameters'
            } finally {
                this.loading = false
            }
        },
        async loadNetworkConnections() {
            this.loading = true
            this.error = null
            try {
                const response = await fetchNetworkConnections(this.axios)
                this.networkConnections = response.data

                // If we get only one connection,set it as selected
                if (this.networkConnections.length === 1) {
                    this.selectedNetworkConnection = this.networkConnections[0].id
                }

            } catch (err) {
                this.error = err.message || 'Failed to fetch network connections'
            } finally {
                this.loading = false
            }
        },
        selectNetworkConnection(networkConnectionId) {
            this.selectedNetworkConnection = this.networkConnections.find(
                (networkConnection) => networkConnection.id === networkConnectionId
            )
        },
        async loadNetworkConnectionStations(networkConnectionId) {
            this.loading = true
            this.error = null
            try {
                const response = await fetchNetworkConnectionStations(this.axios, networkConnectionId)
                this.networkConnectionStations[networkConnectionId] = response.data
            } catch (err) {
                this.error = err.message || 'Failed to fetch network connection stations'
            } finally {
                this.loading = false
            }
        },
        selectStation(stationId) {
            if (stationId) {
                this.selectedStation = this.networkConnectionStations[this.selectedNetworkConnection.id].find(
                    (station) => station.id === stationId
                )
            } else {
                this.selectedStation = null
            }
        },

        async loadStationLinkLatestData(stationId) {
            this.loading = true
            this.error = null
            try {
                const response = await fetchStationLinkLatestData(this.axios, stationId)
                return response.data
            } catch (err) {
                this.error = err.message || 'Failed to fetch station link latest data'
            } finally {
                this.loading = false
            }
        }


    },
    getters: {
        getNetworkConnectionStations: (state) => (networkConnectionId) => {
            return state.networkConnectionStations[networkConnectionId] || []
        },
        getNetworkConnectionById: (state) => (networkConnectionId) => {
            return state.networkConnections.find(
                (networkConnection) => networkConnection.id === networkConnectionId
            )
        }
    }
})
