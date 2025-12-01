<template>
  <div class="qc-inspector h-screen flex flex-column surface-ground">

    <div class="surface-card p-3 border-bottom-1 surface-border flex justify-content-between align-items-center">
      <div class="flex align-items-center gap-3">
        <Button icon="pi pi-arrow-left" text rounded @click="goBack"/>
        <div>
          <h2 class="text-xl font-bold m-0">Station Inspector</h2>
          <span class="text-500 text-sm">Analyzing errors for {{ qcStore.apiMonth }}/{{ qcStore.apiYear }}</span>
        </div>
      </div>
      <div class="flex gap-3">
        <div v-for="type in ['SPIKE', 'RANGE', 'STEP', 'PERSISTENCE']" :key="type" class="flex align-items-center">
          <Checkbox v-model="activeFilters" :value="type" :inputId="type"/>
          <label :for="type" class="ml-2 text-sm cursor-pointer">{{ type }}</label>
        </div>
      </div>
    </div>

    <div class="flex flex-1 overflow-hidden">

      <div class="w-20rem surface-card border-right-1 surface-border flex flex-column">
        <div class="p-3 border-bottom-1 surface-border font-bold text-700">
          Detected Issues ({{ filteredFlags.length }})
        </div>

        <div class="overflow-y-auto flex-1 p-2">
          <div v-if="filteredFlags.length === 0" class="text-center p-4 text-500">
            No issues found with current filters.
          </div>

          <div
              v-for="(flag, idx) in filteredFlags"
              :key="idx"
              class="issue-card p-3 mb-2 border-round surface-50 cursor-pointer transition-colors border-left-3 border-red-500 hover:surface-100"
              @click="zoomToTimestamp(flag.x)"
          >
            <div class="flex justify-content-between mb-1">
              <Badge :value="flag.type" severity="danger" size="small"></Badge>
              <small class="text-500">{{ formatTime(flag.x) }}</small>
            </div>
            <div class="text-sm text-900 line-height-3">{{ flag.text }}</div>
          </div>
        </div>
      </div>

      <div class="flex-1 p-3 relative">
        <div v-if="qcStore.loadingRecords"
             class="absolute inset-0 flex align-items-center justify-content-center z-5 bg-white-alpha-80">
          <ProgressSpinner/>
        </div>

        <Chart :options="chartOptions" :constructor-type="'stockChart'" class="h-full w-full" ref="chartRef"/>
      </div>
    </div>
  </div>
</template>

<script setup>
import {computed, onMounted, ref} from 'vue'
import {useQCStore} from '@/stores/qc'
import {Chart} from 'highcharts-vue'
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import Badge from 'primevue/badge'
import ProgressSpinner from 'primevue/progressspinner'
import * as Highcharts from "highcharts";
import "highcharts/modules/stock";

// Load Highcharts modules
const props = defineProps({
  apiUrl: {
    type: String,
    required: true
  },
  stationId: {
    type: String,
    required: true
  },
  apiYear: {
    type: Number,
    required: true
  },
  apiMonth: {
    type: Number,
    required: true
  },
  languageCode: {
    type: String,
    required: false,
    default: 'en'
  },
});

const qcStore = useQCStore()
const chartRef = ref(null)
const activeFilters = ref(['SPIKE', 'RANGE', 'STEP', 'PERSISTENCE'])

// Filter the flags based on checkbox selection
const filteredFlags = computed(() => {
  if (!qcStore.qcMessages) return []
  return qcStore.qcMessages.filter(f => activeFilters.value.includes(f.type))
})

// Chart Configuration
const chartOptions = computed(() => ({
  chart: {zoomType: 'x'},
  rangeSelector: {enabled: false}, // We control range via clicks
  title: {text: undefined},
  xAxis: {type: 'datetime', ordinal: false},
  yAxis: {
    title: {text: 'Value'},
    plotLines: [{value: 0, width: 1, color: '#eee'}]
  },
  tooltip: {split: true},
  series: [
    // Series 1: The Observation Line
    {
      type: 'line',
      name: 'Observation',
      data: qcStore.records.map(r => [r.x, r.y]),
      id: 'dataseries',
      color: '#2563eb',
      lineWidth: 1,
      states: {hover: {lineWidth: 2}}
    },
    // Series 2: The QC Flags (Pins)
    {
      type: 'flags',
      data: filteredFlags.value,
      onSeries: 'dataseries',
      shape: 'circlepin',
      width: 16,
      color: '#ef4444', // Red
      fillColor: '#ef4444',
      style: {color: 'white'},
      y: -30, // Lift pin above line
      tooltip: {
        pointFormat: '<b>{point.type}</b><br>{point.text}'
      }
    }
  ]
}))

// Format helper
const formatTime = (ts) => new Date(ts).toLocaleString()

// Interaction: Click sidebar item -> Zoom chart
const zoomToTimestamp = (timestamp) => {
  const chart = chartRef.value.chart
  const windowSize = 12 * 60 * 60 * 1000 // 12 hour window
  chart.xAxis[0].setExtremes(timestamp - windowSize, timestamp + windowSize)
  chart.showResetZoom()
}

const goBack = () => {
  window.history.back()
}

onMounted(() => {
  // Load data using the month/year already selected in the Store
  qcStore.loadInspectionData(props.stationId, props.apiMonth, props.apiYear)
})
</script>

<style scoped>
.issue-card:hover {
  border-color: var(--primary-500) !important;
}
</style>