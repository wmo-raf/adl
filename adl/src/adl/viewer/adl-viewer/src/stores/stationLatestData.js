import {defineStore} from 'pinia'
import {format as dateFormat} from "date-fns";

import {fetchStationLinkLatestData} from '@/services/adlService'
import {useStationStore} from "@/stores/station.js";

export const useStationLatestDataStore = defineStore('stationLatestData', {
    state: () => ({
        selectedStationLatestData: null,
        selectedDataCategoryId: null,
        loading: false,
        error: null,
    }),
    actions: {
        async loadStationLinkLatestData(stationId) {
            const stationStore = useStationStore()
            this.loading = true
            this.error = null
            try {
                const response = await fetchStationLinkLatestData(this.axios, stationId)
                const {data} = response
                const stationDataParameters = stationStore.selectedStationDataParameters
                const dataWithParameters = data.data.reduce((all, item) => {
                    const parameter = stationDataParameters.find(p => p.id === item.parameter_id)

                    if (parameter) {
                        const unit = parameter.unit.symbol || ''
                        const paramNameWithUnit = parameter.name + (unit ? ` (${unit})` : '')
                        all.push({
                            ...item,
                            time: dateFormat(item.time, 'dd/MM/yyyy HH:mm'),
                            parameter:
                            paramNameWithUnit,
                            parameterCategory: parameter.category,
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
        clearData() {
            this.selectedStationLatestData = null
        },
        selectDataCategoryId(dataCategoryId) {
            this.selectedDataCategoryId = dataCategoryId
        },
    },
})
