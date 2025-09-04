<script setup>
import Button from 'primevue/button';

import {useStationChartStore} from '@/stores/stationChart'

import ChartPanel from '@/components/chart-view/ChartPanel.vue'
import {onMounted} from "vue";
import {useNetworkStore} from "@/stores/network.js";


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

const addChart = () => {
  chartStore.addChart()
}


onMounted(() => {
  networkStore.loadNetworkConnections()
})

</script>

<template>
  <div>

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

.add-chart-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 400px;
  border: 1px dashed var(--p-primary-color);

}

</style>

