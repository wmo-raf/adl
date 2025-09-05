<script setup>
import {computed, ref, watch} from 'vue';
import DataTable from 'primevue/datatable';
import Button from 'primevue/button';
import Column from 'primevue/column';
import SelectButton from "primevue/selectbutton";
import DatePicker from 'primevue/datepicker';

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
  const startDate = stationTimeseriesDataStore.startDate
  const endDate = stationTimeseriesDataStore.endDate

  const options = {
    page,
    startDate,
    endDate,
  }

  if (category) {
    options.category = category
  }

  stationTimeseriesDataStore.loadStationLinkTimeseriesData(stationStore.selectedStationId, {...options})
}

const dataCategories = computed(() => {
  const categories = stationStore.selectedStationDataCategories
  const filterableDataParameterCategoryIds = stationStore.getFilterableDataParameterCategoryIds

  if (categories && categories.length > 0) {
    return categories.filter((category) => filterableDataParameterCategoryIds.includes(category.id))
  }
  return []
})


watch(() => stationStore.selectedStationLinkDetail, (newStationDetail) => {
  if (newStationDetail?.data_dates) {
    const {latest_time, earliest_time} = newStationDetail.data_dates;

    if (!latest_time || !earliest_time) {
      return;
    }

    const end = new Date(latest_time)

    // Default to 1 day before the end date, or the earliest date if less than 1 day of data
    let start = new Date(end)
    start.setDate(end.getDate() - 1)

    if (start < new Date(earliest_time)) {
      start = new Date(earliest_time)
    }

    stationTimeseriesDataStore.setStartDate(start)
    stationTimeseriesDataStore.setEndDate(end)
  }
}, {immediate: true})


watch(
    () => ({
      stationId: stationStore.selectedStationId,
      categoryId: stationTimeseriesDataStore.selectedDataCategoryId,
      startDate: stationTimeseriesDataStore.startDate,
      endDate: stationTimeseriesDataStore.endDate,
    }),
    ({stationId, categoryId, startDate, endDate}) => {
      if (stationId && categoryId && startDate && endDate) {
        stationTimeseriesDataStore.clearData()

        startDate.setHours(0, 0, 0, 0)
        endDate.setHours(23, 59, 59, 999);

        stationTimeseriesDataStore.loadStationLinkTimeseriesData(stationId, {
          page: 1,
          category: categoryId,
          startDate,
          endDate
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


const maxDate = computed(() => {
  if (stationStore.selectedStationLinkDetail?.data_dates?.latest_time) {
    return new Date(stationStore.selectedStationLinkDetail.data_dates.latest_time)
  }
  return null
})

const minDate = computed(() => {
  if (stationStore.selectedStationLinkDetail?.data_dates?.earliest_time) {
    return new Date(stationStore.selectedStationLinkDetail.data_dates.earliest_time)
  }
  return null
})

</script>
<template>
  <div v-if="maxDate && minDate">
    <div class="date-selectors">
      <div class="c-selector">
        <div class="c-selector-title">
          Start Date
        </div>
        <div>
          <DatePicker
              v-model="stationTimeseriesDataStore.startDate"
              size="small"
              showIcon
              iconDisplay="input"
              dateFormat="dd-mm-yy"
              :maxDate="stationTimeseriesDataStore.endDate"
              :minDate="minDate"
          />
        </div>
      </div>

      <div class="c-selector">
        <div class="c-selector-title">
          End Date
        </div>
        <div>
          <DatePicker
              v-model="stationTimeseriesDataStore.endDate"
              size="small"
              showIcon
              iconDisplay="input"
              dateFormat="dd-mm-yy"
              :minDate="stationTimeseriesDataStore.startDate"
              :maxDate="maxDate"
          />
        </div>
      </div>
    </div>
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
  </div>
</template>

<style>

.date-selectors {
  display: flex;
  gap: 20px;
  margin-bottom: 20px;
  align-items: center;
}

.p-inputtext-sm {
  line-height: normal !important;
  min-height: initial !important;
}

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
  justify-content: center;
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