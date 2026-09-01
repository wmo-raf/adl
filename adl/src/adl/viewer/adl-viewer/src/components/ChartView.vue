<script setup>
import Button from 'primevue/button';
import Message from 'primevue/message';

import {useStationChartStore} from '@/stores/stationChart'

import ChartPanel from '@/components/chart-view/ChartPanel.vue'
import {onMounted} from "vue";
import {useNetworkStore} from "@/stores/network.js";
import {useChartUrlState} from "@/composables/useChartUrlState.js";


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

const networkStore = useNetworkStore()

const chartStore = useStationChartStore()
const urlState = useChartUrlState()

const addChart = () => {
  chartStore.addChart()
}


onMounted(() => {
  networkStore.loadNetworkConnections()
  urlState.initFromUrl()
})

</script>

<template>
  <div>

    <Message v-if="urlState.warnings.value.length && !urlState.warningsDismissed.value"
             severity="warn" :closable="true" class="url-warnings"
             @close="urlState.dismissWarnings">
      <ul class="url-warnings-list">
        <li v-for="warning in urlState.warnings.value" :key="warning">{{ warning }}</li>
      </ul>
    </Message>

    <ChartPanel
        v-for="chart in chartStore.charts"
        :key="chart.id"
        :chart-id="chart.id"
    />


    <div class="add-chart-container">
      <div>
        <Button label="Add Chart" icon="pi pi-plus" @click="addChart" class="mb-4"/>
      </div>
    </div>

  </div>
</template>

<style scoped>

.url-warnings {
  margin-bottom: 20px;
}

.url-warnings-list {
  margin: 0;
  padding-left: 18px;
}

.add-chart-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 400px;
  border: 1px dashed var(--p-primary-color);

}

</style>

