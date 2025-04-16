import {defineStore} from 'pinia'
import {keyBy} from "lodash";

import {fetchDataParameters} from '@/services/adlService'

export const useDataParameterStore = defineStore('dataParameter', {
    state: () => ({
        dataParameterCategories: [],
        dataParameters: {},
        loading: false,
        error: null
    }),
    actions: {
        async loadDataParameters() {
            this.loading = true
            this.error = null
            try {
                const response = await fetchDataParameters(this.axios)
                const {categories, data_parameters} = response.data
                this.dataParameterCategories = categories
                this.dataParameters = keyBy(data_parameters, "id")
            } catch (err) {
                this.error = err.message || 'Failed to fetch data parameters'
            } finally {
                this.loading = false
            }
        },
    },
});