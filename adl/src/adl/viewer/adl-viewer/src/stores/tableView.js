import {defineStore} from 'pinia'
import {keyBy} from "lodash";
import {format as dateFormat} from "date-fns";

import {
    fetchDataParameters,
    fetchNetworkConnections,
    fetchNetworkConnectionStations,
    fetchStationLinkDetail,
    fetchStationLinkLatestData,
    fetchStationLinkTimeseriesData
} from '@/services/adlService'

export const useTableViewStore = defineStore('tableView', {
    state: () => ({
        dataParameters: {},
        networkConnections: [],
        selectedNetworkConnection: null,
        networkConnectionStations: {},
        selectedStation: null,
        selectedStationLinkDetail: null,
        selectedStationLatestData: null,
        selectedStationTimeseriesData: null,
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
        async loadStationLinkDetail(stationId) {
            this.loading = true
            this.error = null
            try {
                const response = await fetchStationLinkDetail(this.axios, stationId)
                this.selectedStationLinkDetail = response.data
            } catch (err) {
                this.error = err.message || 'Failed to fetch station link detail'
            } finally {
                this.loading = false
            }
        },
        clearStationState() {
            this.selectedStation = null
            this.selectedStationLinkDetail = null
            this.selectedStationLatestData = null
            this.selectedStationTimeseriesData = null
        },
        clearStationData() {
            this.selectedStationLinkDetail = null
            this.selectedStationLatestData = null
            this.selectedStationTimeseriesData = null
        },
        async loadStationLinkLatestData(stationId) {
            this.loading = true
            this.error = null
            try {
                const response = await fetchStationLinkLatestData(this.axios, stationId)
                const {data} = response
                const dataWithParameters = data.data.reduce((all, item) => {
                    const parameter = this.dataParameters[item.parameter_id]
                    if (parameter) {
                        const unit = parameter.unit.symbol || ''
                        const paramNameWithUnit = parameter.name + (unit ? ` (${unit})` : '')
                        all.push({
                            ...item,
                            time: dateFormat(item.time, 'dd/MM/yyyy HH:mm'),
                            parameter:
                            paramNameWithUnit,
                            value:
                                item.value.toFixed(2)
                        })
                    }
                    return all
                }, []);

                this.selectedStationLatestData = dataWithParameters
            } catch (err) {
                this.error = err.message || 'Failed to fetch station link latest data'
            } finally {
                this.loading = false
            }
        },
        async loadStationLinkTimeseriesData(stationId) {
            this.loading = true
            this.error = null
            try {
                const response = await fetchStationLinkTimeseriesData(this.axios, stationId)
                const {data} = response

                const uniqueParameters = new Set()

                const normalizedData = data.map(entry => {
                    const flat = {time: dateFormat(entry.time, 'dd/MM/yyyy HH:mm'),};
                    for (const [k, v] of Object.entries(entry.data)) {
                        const parameter = this.dataParameters[k]
                        const unit = parameter.unit.symbol || ''
                        const paramNameWithUnit = parameter.name + (unit ? ` (${unit})` : '')
                        uniqueParameters.add(paramNameWithUnit)
                        if (parameter) {
                            flat[paramNameWithUnit] = v.toFixed(2);
                        }
                    }
                    return flat;
                })

                this.selectedStationTimeseriesData = {
                    data: normalizedData,
                    parameters: Array.from(uniqueParameters)
                }
            } catch (err) {
                this.error = err.message || 'Failed to fetch station link timeseries data'
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
