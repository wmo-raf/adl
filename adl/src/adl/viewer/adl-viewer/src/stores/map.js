import {defineStore} from 'pinia'

export const useMapStore = defineStore('map', {
    state: () => ({
        selectedDataParameterId: null,
        selectedDateTime: null,
        isCurrentTime: true,
        loading: false,
        error: null
    }),
    actions: {
        selectNetworkConnection(selectedDataParameterId) {
            this.selectedDataParameterId = selectedDataParameterId
        },
        setSelectedDateTime(dateTime, isCurrent) {
            this.selectedDateTime = dateTime;
            this.isCurrentTime = isCurrent;
        },
        clearDataParameterState() {
            this.selectedDataParameterId = null
            this.selectedDateTime = null;
            this.isCurrentTime = true;
        }
    },
})