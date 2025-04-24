<script setup>
import {computed} from 'vue'
import {useStationChartStore} from '@/stores/stationChart'
import {useNetworkStore} from "@/stores/network.js";
import {parseISO} from 'date-fns'
import Select from 'primevue/select'
import Panel from "primevue/panel";
import {Chart} from 'highcharts-vue';

const props = defineProps({
  chartId: String,
  stations: Array,
  parameters: Array,
})

const chartStore = useStationChartStore()
const networkStore = useNetworkStore()

const chart = computed(() => chartStore.charts[props.chartId])

const onNetworkConnChange = () => {
  chartStore.updateChartConfig(props.chartId, {
    connectionId: chart.value.connectionId,
    stationId: null,
    dataParameterId: null,
    stationDetail: null,
    timeseriesData: null,
  })
  chartStore.loadConnectionStations(chart.value.connectionId)
}

const onStationChange = () => {
  chartStore.updateChartConfig(props.chartId, {
    connectionId: chart.value.connectionId,
    stationId: chart.value.stationId,
    stationDetail: null,
    dataParameterId: null,
    timeseriesData: null,
  })

  chartStore.loadStationDetail(props.chartId, chart.value.stationId)
}

const onParameterChange = () => {
  chartStore.loadChartData(props.chartId)
}


const connectionStationLinks = computed(() => {
  const connectionId = chart.value.connectionId
  return networkStore.networkConnectionStations[connectionId] || []
})

const remove = () => chartStore.removeChart(props.chartId)

const highchartsOptions = computed(() => {
  const chart = chartStore.charts[props.chartId];

  if (!chart || !chart.timeseriesData) {
    return null;
  }

  const tsData = chart.timeseriesData.reduce((acc, d) => {
    const time = parseISO(d.time).getTime()
    const value = d.data[chart.dataParameterId]
    if (value !== null && value !== undefined) {
      acc.push([time, value])
    }
    return acc
  }, []).sort((a, b) => a[0] - b[0])

  const chartTitle = chart.stationDetail?.station ? chart.stationDetail.station.name : ""
  const dataParameter = chart.stationDetail?.data_parameters.find(p => p.id === chart.dataParameterId)
  const unit = dataParameter?.unit?.name || ""
  const parameterName = dataParameter ? `${dataParameter.name} (${unit})` : ""

  return {
    chart: {
      type: 'line',
    },
    time: {
      timezone: undefined
    },
    title: {
      text: chartTitle,
    },
    legend: {
      enabled: true,
      align: 'center',
      verticalAlign: 'top',
    },
    xAxis: {
      type: 'datetime',
    },
    yAxis: {
      title: {
        text: parameterName,
      },
      startOnTick: false,
    },
    series: [{
      name: parameterName,
      data: tsData,
      color: 'red',
    }],
    tooltip: {
      xDateFormat: '%Y-%m-%d %H:%M',
      valueDecimals: 2,
    },
    plotOptions: {
      series: {
        connectNulls: false,
        marker: {
          enabled: false,
        },
      },
    },
  };
});

</script>

<template>
  <Panel
      class="chart-panel"
      toggleable
      :pt="{ header: { class: 'c-header' } }"
  >
    <template #header>
      <div class="c-selectors">
        <div class="c-selector">
          <div class="c-selector-title">
            Select Network Connection
          </div>
          <Select
              v-model="chart.connectionId"
              :options="networkStore.networkConnections"
              optionLabel="name"
              optionValue="id"
              placeholder="Select Connection"
              @change="onNetworkConnChange"
          />
        </div>
        <div class="c-selector">
          <div class="c-selector-title">
            Select Station
          </div>
          <Select
              v-model="chart.stationId"
              :options="connectionStationLinks"
              optionLabel="station.name"
              optionValue="id"
              placeholder="Select Station"
              @change="onStationChange"
              :disabled="!connectionStationLinks.length"
          />
        </div>
        <div class="c-selector">
          <div class="c-selector-title">
            Select Data Parameter
          </div>
          <Select
              v-model="chart.dataParameterId"
              :options="chart.stationDetail?.data_parameters"
              optionLabel="name"
              optionValue="id"
              placeholder="Select Parameter"
              :disabled="!chart.stationDetail"
              @change="onParameterChange"
          />
        </div>
      </div>
    </template>

    <div class="c-body">
      <Chart
          v-if="highchartsOptions"
          type="line"
          :options="highchartsOptions"
          :height="100"
      />
    </div>

  </Panel>
</template>


<style>
.c-header {
  background: #f1f5f8 !important;
}
</style>


<style scoped>


.chart-panel {
  margin-bottom: 20px;
}


.c-selectors {
  display: flex;
  gap: 10px;
  margin: 20px 0;
}

.c-selector {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.c-selector-title {
  font-size: 14px;
  font-weight: bold;
}

.c-body {
  margin-top: 20px;
  min-height: 400px;
}

@media (max-width: 768px) {
  .c-selectors {
    flex-direction: column;
    gap: 20px;
  }
}

</style>
