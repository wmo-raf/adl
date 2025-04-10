<script setup>
import {onMounted} from "vue";
import Panel from 'primevue/panel';

import {useTableViewStore} from '@/stores/tableView'

import NetworkConnectionSelect from "@/components/table-view/NetworkConnectionSelect.vue";
import StationSelect from "@/components/table-view/StationSelect.vue";

import StationLinkDetail from "@/components/table-view/StationLinkDetail.vue";
import SummaryDataTable from "@/components/table-view/SummaryDataTable.vue";
import TimeSeriesDataTable from "@/components/table-view/TimeSeriesDataTable.vue";


const props = defineProps({
  apiUrl: {
    type: String,
    required: true
  },
  languageCode: {
    type: String,
    required: false,
    default: 'en'
  },
});

const tableViewStore = useTableViewStore()

onMounted(() => {
  tableViewStore.loadDataParameters()
})

</script>

<template>
  <Panel>
    <div class="tv-header">
      <NetworkConnectionSelect/>
      <StationSelect/>
    </div>
  </Panel>

  <Panel v-if="tableViewStore.selectedStation" class="tv-station-detail" header="Station Detail" toggleable>
    <StationLinkDetail/>
  </Panel>

  <Panel v-if="tableViewStore.selectedStation" class="tv-summary-table" header="Summary Data" toggleable>
    <SummaryDataTable/>
  </Panel>

  <Panel v-if="tableViewStore.selectedStation" class="tv-timeseries-table" header="Station Data" toggleable>
    <TimeSeriesDataTable/>
  </Panel>
</template>

<style scoped>

.tv-header {
  display: flex;
  gap: 40px;
}

@media (max-width: 768px) {
  .tv-header {
    flex-direction: column;
    gap: 20px;
  }
}

.tv-station-detail {
  margin-top: 20px;
}

.tv-summary-table {
  margin-top: 20px;
}

.tv-timeseries-table {
  margin-top: 20px;
}

</style>