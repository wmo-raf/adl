import {defineStore} from 'pinia'

import {
    fetchNetworkConnectionDataParameters,
    fetchNetworkConnections,
    fetchNetworkConnectionStations
} from '@/services/adlService'

export const useNetworkStore = defineStore('network', {
    state: () => ({
        networkConnections: [],
        selectedNetworkConnection: null,
        networkConnectionStations: {},
        networkConnectionDataParameters: {},
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
        async loadNetworkConnectionDataParameters(networkConnectionId) {
            this.loading = true
            this.error = null
            try {
                const response = await fetchNetworkConnectionDataParameters(this.axios, networkConnectionId)
                this.networkConnectionDataParameters[networkConnectionId] = response.data
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
        },
        getNetworkConnectionDataParameters: (state) => (networkConnectionId) => {
            return state.networkConnectionDataParameters[networkConnectionId] || []
        },
        getSelectedNetworkConnectionDataParameter: (state) => (networkConnectionId, dataParameterId) => {
            const connDataParameters = state.networkConnectionDataParameters[networkConnectionId]
            if (connDataParameters && connDataParameters.length > 0) {
                return connDataParameters.find(dataParameter => dataParameter.id === dataParameterId)
            }
        }
    }
})
