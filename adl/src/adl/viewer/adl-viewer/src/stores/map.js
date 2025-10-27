import {defineStore} from 'pinia'

export const useMapStore = defineStore('map', {
    state: () => ({
        selectedDataParameterId: null,
        visualizationType: 'circle',
        setVisualizationType(type) {
            this.visualizationType = type;
        },
        loading: false,
        error: null
    }),
    actions: {
        selectNetworkConnection(selectedDataParameterId) {
            this.selectedDataParameterId = selectedDataParameterId
        },
        clearDataParameterState() {
            this.selectedDataParameterId = null
            this.visualizationType = 'circle';
        }
    },
})