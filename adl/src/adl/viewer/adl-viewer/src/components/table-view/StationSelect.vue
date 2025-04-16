<script setup>
import {computed, watch} from 'vue'
import Select from 'primevue/select';

import {useStationStore} from "@/stores/station.js";
import {useNetworkStore} from "@/stores/network.js";

const stationStore = useStationStore()
const networkStore = useNetworkStore()

const selectedNetworkConnectionStations = computed(() => {
  const selectedNetworkConnection = networkStore.selectedNetworkConnection
  return networkStore.getNetworkConnectionStations(selectedNetworkConnection)
});


watch(() => networkStore.selectedNetworkConnection, (newValue) => {
  if (newValue) {
    stationStore.clearStationState()
  }
}, {immediate: true})

</script>

<template>
  <div class="c-selector">
    <div class="c-selector-title">
      Select Station
    </div>
    <Select v-model="stationStore.selectedStationId"
            :options="selectedNetworkConnectionStations"
            :disabled="!networkStore.selectedNetworkConnection"
            :loading="stationStore.loading"
            optionLabel="station.name"
            optionValue="id"
            placeholder="Select a station"
    />
  </div>
</template>

<style scoped>

.c-selector {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.c-selector-title {
  font-size: 14px;
  font-weight: bold;
}

</style>