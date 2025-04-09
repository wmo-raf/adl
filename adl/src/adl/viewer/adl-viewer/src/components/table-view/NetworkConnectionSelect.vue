<script setup>
import {onMounted, watch} from 'vue'
import Select from 'primevue/select';

import {useTableViewStore} from '@/stores/tableView'

const tableViewStore = useTableViewStore()

onMounted(() => {
  tableViewStore.loadNetworkConnections()
})


watch(() => tableViewStore.selectedNetworkConnection, (newValue) => {
  if (newValue) {
    tableViewStore.selectStation(null)
    tableViewStore.clearStationLatestData()

    tableViewStore.loadNetworkConnectionStations(newValue)
  }
}, {immediate: true})


</script>

<template>
  <div class="c-selector">
    <div class="c-selector-title">
      Select Network Connection
    </div>
    <Select v-model="tableViewStore.selectedNetworkConnection"
            :options="tableViewStore.networkConnections"
            optionLabel="name" optionValue="id" placeholder="Select a connection"></Select>
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