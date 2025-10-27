import {defineStore} from 'pinia'

export const useMapStore = defineStore('map', {
    state: () => ({
        selectedDataParameterId: null,
        loading: false,
        error: null
    }),
    actions: {
        selectNetworkConnection(selectedDataParameterId) {
            this.selectedDataParameterId = selectedDataParameterId
        },
        clearDataParameterState() {
            this.selectedDataParameterId = null
        }
    },
})