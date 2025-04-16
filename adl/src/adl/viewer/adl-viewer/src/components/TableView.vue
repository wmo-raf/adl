<script setup>
import {onMounted} from "vue";
import Panel from 'primevue/panel';

import NetworkConnectionSelect from "@/components/table-view/NetworkConnectionSelect.vue";
import StationSelect from "@/components/table-view/StationSelect.vue";
import StationLinkDetail from "@/components/table-view/StationLinkDetail.vue";
import LatestDataTable from "@/components/table-view/LatestDataTable.vue";
import TimeSeriesDataTable from "@/components/table-view/TimeSeriesDataTable.vue";

import {useDataParameterStore} from "@/stores/dataParameter.js";
import {useStationStore} from "@/stores/station.js";


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

const stationStore = useStationStore()
const dataParameterStore = useDataParameterStore()

onMounted(() => {
  dataParameterStore.loadDataParameters()
})

</script>

<template>
  <Panel>
    <div class="tv-header">
      <NetworkConnectionSelect/>
      <StationSelect/>
    </div>
  </Panel>

  <Panel v-if="stationStore.selectedStationId" class="tv-station-detail" header="Station Detail" toggleable>
    <StationLinkDetail/>
  </Panel>

  <Panel v-if="stationStore.selectedStationId" class="tv-summary-table" header="Latest Data Summary" toggleable>
    <LatestDataTable/>
  </Panel>

  <Panel v-if="stationStore.selectedStationId" class="tv-timeseries-table" header="Station Data" toggleable>
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