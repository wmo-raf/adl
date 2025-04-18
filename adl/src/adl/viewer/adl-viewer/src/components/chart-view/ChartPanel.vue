<script setup>
import {computed} from 'vue'
import {useStationChartStore} from '@/stores/stationChart'
import {useNetworkStore} from "@/stores/network.js";

import Select from 'primevue/select'
import Panel from "primevue/panel";

const props = defineProps({
  chartId: Number,
  stations: Array,
  parameters: Array,
})

const chartStore = useStationChartStore()
const networkStore = useNetworkStore()

const chart = computed(() => chartStore.charts[props.chartId])

const loadData = () => chartStore.loadChartData(props.chartId)

const onConfigChange = () => {

  chartStore.updateChartConfig(props.chartId, {
    connectionId: chart.value.connectionId,
    stationId: chart.value.stationId,
    dataParameterId: chart.value.dataParameterId
  })

  chartStore.loadConnectionStations(chart.value.connectionId)
}

const connectionStationLinks = computed(() => {
  const connectionId = chart.value.connectionId
  return networkStore.networkConnectionStations[connectionId] || []
})

const stationDataParameters = computed(() => {
  const stationId = chart.value.stationId
  return networkStore.networkStationDataParameters[stationId] || []
})

const remove = () => chartStore.removeChart(props.chartId)


</script>

<template>
  <Panel class="chart-panel">
    <Select
        v-model="chart.connectionId"
        :options="networkStore.networkConnections"
        optionLabel="name"
        optionValue="id"
        placeholder="Select Connection"
        @change="onConfigChange"
    />

    <Select
        v-model="chart.stationId"
        :options="connectionStationLinks"
        optionLabel="station.name"
        optionValue="station.id"
        placeholder="Select Station"
    />
  </Panel>
</template>


<style scoped>
.chart-panel {
  margin-bottom: 20px;
}
</style>
