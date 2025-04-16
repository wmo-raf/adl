import {defineStore} from 'pinia'
import {format as dateFormat} from "date-fns";

import {fetchStationLinkTimeseriesData} from '@/services/adlService'
import {useDataParameterStore} from "./dataParameter.js"

export const useStationTimeseriesDataStore = defineStore('stationTimeseriesData', {
    state: () => ({
        selectedStationTimeseriesData: null,
        selectedDataCategoryId: null,
        loading: false,
        error: null
    }),
    actions: {
        async loadStationLinkTimeseriesData(stationId, {page = 1, category} = {}) {
            const dataParameterStore = useDataParameterStore()
            this.loading = true
            this.error = null
            try {
                const response = await fetchStationLinkTimeseriesData(this.axios, stationId, page, category)
                const {data} = response

                const uniqueParameters = new Set()

                const normalizedData = data.results.map(entry => {
                    const flat = {time: dateFormat(entry.time, 'dd/MM/yyyy HH:mm'),};

                    for (const [k, v] of Object.entries(entry.data)) {
                        const parameter = dataParameterStore.dataParameters[k]
                        if (parameter) {
                            const unit = parameter.unit.symbol || ''
                            const paramNameWithUnit = parameter.name + (unit ? ` (${unit})` : '')
                            uniqueParameters.add(paramNameWithUnit)
                            flat[paramNameWithUnit] = v.toFixed(2);
                        }
                    }

                    return flat;
                })

                this.selectedStationTimeseriesData = {
                    total: data.count,
                    data: normalizedData,
                    parameters: Array.from(uniqueParameters)
                }
            } catch (err) {
                this.error = err.message || 'Failed to fetch station link timeseries data'
            } finally {
                this.loading = false
            }
        },
        clearData() {
            this.selectedStationTimeseriesData = null
        },
        selectDataCategoryId(dataCategoryId) {
            this.selectedDataCategoryId = dataCategoryId
        },
    },
})
