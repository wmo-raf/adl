<script setup>
import {computed, onMounted, watch} from 'vue'
import Select from 'primevue/select';

import {useTableViewStore} from '@/stores/tableView'

const tableViewStore = useTableViewStore()

onMounted(() => {
  tableViewStore.loadNetworkConnections()
})

const selectedNetworkConnectionStations = computed(() => {
  const selectedNetworkConnection = tableViewStore.selectedNetworkConnection
  return tableViewStore.getNetworkConnectionStations(selectedNetworkConnection)
})


watch(() => tableViewStore.selectedStation, (newValue) => {
  if (newValue) {
    tableViewStore.loadStationLinkLatestData(newValue)
  }
}, {immediate: true})

</script>

<template>
  <div class="c-selector">
    <div class="c-selector-title">
      Select Station
    </div>
    <Select v-model="tableViewStore.selectedStation"
            :options="selectedNetworkConnectionStations"
            :disabled="!tableViewStore.selectedNetworkConnection"
            :loading="tableViewStore.loading"
            optionLabel="station.name" optionValue="id" placeholder="Select a station"/>
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