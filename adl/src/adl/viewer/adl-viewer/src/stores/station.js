import {defineStore} from 'pinia'

import {fetchStationLinkDetail} from '@/services/adlService'

export const useStationStore = defineStore('stationInfo', {
    state: () => ({
        selectedStationId: null,
        selectedStationLinkDetail: null,
        selectedStationDataParameters: [],
        selectedStationDataCategories: [],
        loading: false,
        error: null
    }),
    actions: {
        selectStation(stationId) {
            if (stationId) {
                this.selectedStationId = stationId
            } else {
                this.selectedStationId = null
            }
        },
        async loadStationLinkDetail(stationId) {
            this.loading = true
            this.error = null
            try {
                const response = await fetchStationLinkDetail(this.axios, stationId)
                const {data_parameters, data_categories} = response.data
                this.selectedStationLinkDetail = response.data
                this.selectedStationDataParameters = data_parameters || []
                this.selectedStationDataCategories = data_categories || []
            } catch (err) {
                this.error = err.message || 'Failed to fetch station link detail'
            } finally {
                this.loading = false
            }
        },
        clearStationState() {
            this.selectedStationId = null
            this.selectedStationLinkDetail = null
            this.selectedStationDataParameters = []
            this.selectedStationDataCategories = []
        },
    },
    getters: {
        getFilterableDataParameterCategoryIds: (state) => {
            const filterableDataParameterCategoryIds = state.selectedStationDataParameters
                .map((parameter) => parameter.category)
            return [...new Set(filterableDataParameterCategoryIds)]
        }
    }
})
