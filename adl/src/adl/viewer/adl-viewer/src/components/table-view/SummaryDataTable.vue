<script setup>

import DataTable from 'primevue/datatable';
import Column from 'primevue/column';
import {useTableViewStore} from '@/stores/tableView'

const tableViewStore = useTableViewStore()


</script>

<template>
  <DataTable :value="tableViewStore.selectedStationLatestData" :size="'small'" stripedRows
             :loading="tableViewStore.loading" scrollable>
    <Column field="parameter" header="Parameter" style="max-width: 100px"></Column>
    <Column field="time" header="Time"></Column>
    <Column field="value" header="Last Report"></Column>
  </DataTable>
</template>

<style scoped>

</style>