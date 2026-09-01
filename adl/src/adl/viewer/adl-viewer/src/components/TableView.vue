<script setup>
import {onMounted} from "vue";
import Panel from 'primevue/panel';
import Message from 'primevue/message';

import Tabs from 'primevue/tabs';
import TabList from 'primevue/tablist';
import Tab from 'primevue/tab';
import TabPanels from 'primevue/tabpanels';
import TabPanel from 'primevue/tabpanel';


import NetworkConnectionSelect from "@/components/table-view/NetworkConnectionSelect.vue";
import StationSelect from "@/components/table-view/StationSelect.vue";
import StationLinkDetail from "@/components/table-view/StationLinkDetail.vue";
import TimeSeriesDataTable from "@/components/table-view/TimeSeriesDataTable.vue";

import {useDataParameterStore} from "@/stores/dataParameter.js";
import {useStationStore} from "@/stores/station.js";
import {useTableUrlState} from "@/composables/useTableUrlState.js";


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
const urlState = useTableUrlState()

onMounted(() => {
  dataParameterStore.loadDataParameters()
  urlState.initFromUrl()
})

</script>

<template>
  <Message v-if="urlState.warnings.value.length && !urlState.warningsDismissed.value"
           severity="warn" :closable="true" class="url-warnings"
           @close="urlState.dismissWarnings">
    <ul class="url-warnings-list">
      <li v-for="warning in urlState.warnings.value" :key="warning">{{ warning }}</li>
    </ul>
  </Message>

  <Panel>
    <div class="tv-header">
      <NetworkConnectionSelect/>
      <StationSelect/>
    </div>
  </Panel>

  <Panel v-if="stationStore.selectedStationId" class="tv-station-detail" header="Station Detail" toggleable>
    <StationLinkDetail/>
  </Panel>


  <section class="data-section" v-if="stationStore.selectedStationId">
    <Tabs value="historical" lazy>
      <TabList>
        <Tab value="historical">
          <div class="tab-title">
            <i class="pi pi-database"/>
            <span>Station Data</span>
          </div>
        </Tab>
      </TabList>
      <TabPanels>
        <TabPanel value="historical">
          <TimeSeriesDataTable/>
        </TabPanel>
      </TabPanels>
    </Tabs>
  </section>

</template>

<style scoped>

.url-warnings {
  margin-bottom: 20px;
}

.url-warnings-list {
  margin: 0;
  padding-left: 18px;
}

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

.data-section {
  margin-top: 20px;
}

.tab-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

</style>