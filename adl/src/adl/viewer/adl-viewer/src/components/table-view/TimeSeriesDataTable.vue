<script setup>
import {ref} from 'vue';

import DataTable from 'primevue/datatable';
import Button from 'primevue/button';
import Column from 'primevue/column';
import {useTableViewStore} from '@/stores/tableView'

const tableViewStore = useTableViewStore()

const dt = ref();
const exportCSV = () => {
  dt.value.exportCSV();
};

</script>
<template>
  <DataTable ref="dt" v-if="tableViewStore.selectedStationTimeseriesData"
             :value="tableViewStore.selectedStationTimeseriesData.data" :size="'small'" stripedRows
             :loading="tableViewStore.loading"
             scrollable
             scrollHeight="85vh"
  >
    <template #header>
      <div class="ts-header">
        <Button icon="pi pi-external-link" label="Export" @click="exportCSV($event)"/>
      </div>
    </template>
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

.ts-header {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 10px;
}

</style>