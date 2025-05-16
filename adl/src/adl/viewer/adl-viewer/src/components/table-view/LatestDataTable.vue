<script setup>
import DataTable from 'primevue/datatable';
import Column from 'primevue/column';
import SelectButton from 'primevue/selectbutton';
import {computed, watch} from "vue";
import {useStationLatestDataStore} from "@/stores/stationLatestData.js";
import {useStationStore} from "@/stores/station.js";

const stationStore = useStationStore()
const stationLatestDataStore = useStationLatestDataStore()

const dataCategories = computed(() => {
  const categories = stationStore.selectedStationDataCategories
  const filterableDataParameterCategoryIds = stationStore.getFilterableDataParameterCategoryIds

  if (categories && categories.length > 0) {
    return categories.filter((category) => filterableDataParameterCategoryIds.includes(category.id))
  }
  return []
})

const filteredData = computed(() => {
  let selectedCategoryId = stationLatestDataStore.selectedDataCategoryId

  if (!selectedCategoryId && stationStore.selectedStationDataCategories && stationStore.selectedStationDataCategories.length > 0) {
    selectedCategoryId = stationStore.selectedStationDataCategories[0].id
  }

  if (selectedCategoryId) {
    const data = stationLatestDataStore.selectedStationLatestData
    return data && data.filter((item) => item.parameterCategory === selectedCategoryId)
  }
  return stationLatestDataStore.selectedStationLatestData
});

// fetch new data when station is changed
watch(() => stationStore.selectedStationId, (newStationId) => {
  if (newStationId) {
    stationLatestDataStore.clearData()
    stationLatestDataStore.loadStationLinkLatestData(newStationId)
  }
}, {immediate: true})

// fetch new data when station is changed
watch(() => stationStore.selectedStationDataCategories, (newDataCategories) => {
  if (newDataCategories && !!newDataCategories.length) {
    stationLatestDataStore.selectDataCategoryId(newDataCategories[0].id)
  }
}, {immediate: true})

</script>

<template>
  <div class="c-selector" v-if="dataCategories && dataCategories.length > 1">
    <div class="c-selector-title">
      Data Category
    </div>
    <SelectButton
        v-model="stationLatestDataStore.selectedDataCategoryId"
        :options="dataCategories"
        optionLabel="name"
        optionValue="id"
        placeholder="Select a category"
    />
  </div>

  <DataTable
      :value="filteredData"
      :size="'small'"
      stripedRows
      :loading="stationLatestDataStore.loading"
      scrollable>
    <Column field="parameter" header="Parameter" style="max-width: 100px"></Column>
    <Column field="time" header="Time"></Column>
    <Column field="value" header="Last Report"></Column>
  </DataTable>
</template>

<style scoped>

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

</style>