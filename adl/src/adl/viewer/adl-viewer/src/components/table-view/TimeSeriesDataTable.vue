<script setup>
import {computed, ref, watch} from 'vue';
import DataTable from 'primevue/datatable';
import Button from 'primevue/button';
import Column from 'primevue/column';
import SelectButton from "primevue/selectbutton";

import {useStationTimeseriesDataStore} from "@/stores/stationTimeseriesData.js";
import {useStationStore} from "@/stores/station.js";

const stationStore = useStationStore()
const stationTimeseriesDataStore = useStationTimeseriesDataStore()

const dt = ref();
const exportCSV = () => {
  dt.value.exportCSV();
};


const onPage = (event) => {
  const page = event.page + 1 // PrimeVue is 0-based, backend is 1-based
  const category = stationTimeseriesDataStore.selectedDataCategoryId

  if (category) {
    stationTimeseriesDataStore.loadStationLinkTimeseriesData(stationStore.selectedStationId, {page, category})
  } else {
    stationTimeseriesDataStore.loadStationLinkTimeseriesData(stationStore.selectedStationId, {page})
  }
}

const dataCategories = computed(() => {
  const categories = stationStore.selectedStationDataCategories
  const filterableDataParameterCategoryIds = stationStore.getFilterableDataParameterCategoryIds

  if (categories && categories.length > 0) {
    return categories.filter((category) => filterableDataParameterCategoryIds.includes(category.id))
  }
  return []
})

watch(
    () => ({
      stationId: stationStore.selectedStationId,
      categoryId: stationTimeseriesDataStore.selectedDataCategoryId,
    }),
    ({stationId, categoryId}) => {
      if (stationId && categoryId) {
        stationTimeseriesDataStore.clearData()
        stationTimeseriesDataStore.loadStationLinkTimeseriesData(stationId, {
          page: 1,
          category: categoryId,
        })
      }
    },
    {immediate: true}
)


watch(() => stationStore.selectedStationDataCategories, (newDataCategories) => {
  if (newDataCategories && !!newDataCategories.length) {
    stationTimeseriesDataStore.selectDataCategoryId(newDataCategories[0].id)
  }
}, {immediate: true})


</script>
<template>
  <div class="c-selector" v-if="dataCategories && dataCategories.length > 1">
    <div class="c-selector-title">
      Data Category
    </div>
    <SelectButton
        v-model="stationTimeseriesDataStore.selectedDataCategoryId"
        :options="dataCategories"
        optionLabel="name"
        optionValue="id"
        placeholder="Select a category"
    />
  </div>

  <DataTable
      ref="dt"
      v-if="stationTimeseriesDataStore.selectedStationTimeseriesData"
      :value="stationTimeseriesDataStore.selectedStationTimeseriesData.data"
      size="small"
      stripedRows
      :loading="stationTimeseriesDataStore.loading"
      scrollable
      :paginator="stationTimeseriesDataStore.selectedStationTimeseriesData?.total > 200"
      :lazy="true"
      :totalRecords="stationTimeseriesDataStore.selectedStationTimeseriesData.total"
      :rows="200"
      @page="onPage"
      scrollHeight="50vh"
  >
    <template #header>
      <div class="ts-header">
        <Button icon="pi pi-external-link" label="Export" @click="exportCSV($event)"/>
      </div>
    </template>
    <Column field="time" header="Time" style="min-width: 100px" frozen/>
    <Column
        v-for="col in stationTimeseriesDataStore.selectedStationTimeseriesData.parameters"
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

.c-selector {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 20px;
}

.c-selector-title {
  font-size: 12px;
  font-weight: 600;
}

.ts-header-left {
  display: flex;
  gap: 10px;
}

.start-date-picker input {
  font-size: var(--p-inputtext-sm-font-size);
}

</style>