<script setup>
import {ref} from 'vue';

import DataTable from 'primevue/datatable';
import DatePicker from 'primevue/datepicker';
import Button from 'primevue/button';
import Column from 'primevue/column';
import Select from 'primevue/select';

import {useTableViewStore} from '@/stores/tableView'

const tableViewStore = useTableViewStore()

const dt = ref();
const exportCSV = () => {
  dt.value.exportCSV();
};

const date = ref();

const selectedNoOfDaysBack = ref();
const noOfDaysBack = ref([
  {label: "24 Hours", value: 1},
  {label: "5 Days", value: 5},
  {label: "10 Days", value: 10},
  {label: "30 Days", code: 30},
]);

const onPage = (event) => {
  const page = event.page + 1 // PrimeVue is 0-based, backend is 1-based
  tableViewStore.loadStationLinkTimeseriesData(tableViewStore.selectedStation, {page})
}


</script>
<template>
  <DataTable ref="dt" v-if="tableViewStore.selectedStationTimeseriesData"
             :value="tableViewStore.selectedStationTimeseriesData.data"
             size="small"
             stripedRows
             :loading="tableViewStore.loading"
             scrollable
             paginator
             :lazy="true"
             :totalRecords="tableViewStore.selectedStationTimeseriesData.total"
             :rows="200"
             @page="onPage"
             scrollHeight="50vh"
  >
    <template #header>
      <div class="ts-header">
        <!--        <div class="ts-header-left">-->
        <!--          <div class="c-selector">-->
        <!--            <div class="c-selector-title">-->
        <!--              Select Date-->
        <!--            </div>-->
        <!--            <DatePicker-->
        <!--                v-model="date"-->
        <!--                showTime-->
        <!--                showButtonBar-->
        <!--                stepMinute="5"-->
        <!--                hourFormat="24"-->
        <!--                size="small"-->
        <!--                showIcon-->
        <!--                iconDisplay="input"-->
        <!--                class="start-date-picker"-->
        <!--                placeholder="Select time"-->
        <!--            />-->
        <!--          </div>-->
        <!--          <div class="c-selector">-->
        <!--            <div class="c-selector-title">-->
        <!--              Select No. of Days back-->
        <!--            </div>-->
        <!--            <Select-->
        <!--                v-model="selectedNoOfDaysBack"-->
        <!--                :options="noOfDaysBack"-->
        <!--                optionLabel="label"-->
        <!--                optionValue="value"-->
        <!--                placeholder="Select days"-->
        <!--            />-->
        <!--          </div>-->
        <!--        </div>-->
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

<style>

.ts-header {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 10px;
}

.ts-header-left {
  display: flex;
  gap: 10px;
}

.start-date-picker input {
  font-size: var(--p-inputtext-sm-font-size);
}

</style>