import {defineStore} from 'pinia'

import {fetchNetworkConnections, fetchNetworkConnectionStations} from '@/services/adlService'

export const useNetworkStore = defineStore('network', {
    state: () => ({
        networkConnections: [],
        selectedNetworkConnection: null,
        networkConnectionStations: {},
        loading: false,
        error: null
    }),
    actions: {
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
