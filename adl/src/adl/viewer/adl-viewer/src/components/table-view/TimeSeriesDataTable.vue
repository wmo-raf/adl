<script setup>

import DataTable from 'primevue/datatable';
import Column from 'primevue/column';
import {useTableViewStore} from '@/stores/tableView'

const tableViewStore = useTableViewStore()

</script>
<template>
  <DataTable v-if="tableViewStore.selectedStationTimeseriesData"
             :value="tableViewStore.selectedStationTimeseriesData.data" :size="'small'" stripedRows
             :loading="tableViewStore.loading"
             scrollable
  >
    <Column field="time" header="Time" style="min-width: 100px" frozen/>
    <Column
        v-for="col in tableViewStore.selectedStationTimeseriesData.parameters"
        :key="col"
        :field="col"
        :header="col"
        style="min-width: 50px"
    />
  </DataTable>
</template>

<style scoped>

</style>