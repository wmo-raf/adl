<template>
  <div class="availability-dashboard surface-ground min-h-screen p-4">
    <!-- Header -->
    <div class="surface-card p-4 shadow-2 border-round mb-4">
      <div class="flex flex-column md:flex-row justify-content-between align-items-center gap-3">
        <div>
          <h1 class="text-2xl font-bold m-0 text-900">Data Availability</h1>
          <p class="text-500 m-0 mt-1">
            Last 24 hours · {{ formattedTimeRange }}
          </p>
        </div>

        <div class="flex align-items-center gap-2">
          <Select
              v-model="availabilityStore.selectedConnectionId"
              :options="connections"
              optionLabel="name"
              optionValue="id"
              placeholder="Select Connection"
              class="w-15rem"
              @change="onConnectionChange"
          />

          <Button
              icon="pi pi-refresh"
              rounded
              outlined
              @click="availabilityStore.loadSummary"
              :loading="availabilityStore.loadingSummary"
              aria-label="Refresh"
              v-tooltip.top="'Refresh data'"
          />
        </div>
      </div>
    </div>

    <!-- Summary Stats -->
    <div class="grid mb-4" v-if="availabilityStore.summaryData">
      <div class="col-6 md:col-3">
        <div class="surface-card p-3 shadow-2 border-round">
          <div class="flex align-items-center gap-3">
            <div class="flex align-items-center justify-content-center border-round w-3rem h-3rem bg-blue-100">
              <i class="pi pi-server text-blue-600 text-xl"></i>
            </div>
            <div>
              <div class="text-2xl font-bold text-900">{{ availabilityStore.totalStations }}</div>
              <div class="text-500 text-sm">Total Stations</div>
            </div>
          </div>
        </div>
      </div>

      <div class="col-6 md:col-3">
        <div class="surface-card p-3 shadow-2 border-round">
          <div class="flex align-items-center gap-3">
            <div class="flex align-items-center justify-content-center border-round w-3rem h-3rem bg-green-100">
              <i class="pi pi-check-circle text-green-600 text-xl"></i>
            </div>
            <div>
              <div class="text-2xl font-bold text-green-600">{{ availabilityStore.reportingStations }}</div>
              <div class="text-500 text-sm">Reporting</div>
            </div>
          </div>
        </div>
      </div>

      <div class="col-6 md:col-3">
        <div class="surface-card p-3 shadow-2 border-round">
          <div class="flex align-items-center gap-3">
            <div class="flex align-items-center justify-content-center border-round w-3rem h-3rem bg-yellow-100">
              <i class="pi pi-exclamation-triangle text-yellow-600 text-xl"></i>
            </div>
            <div>
              <div class="text-2xl font-bold text-yellow-600">{{ availabilityStore.stationsWithGaps }}</div>
              <div class="text-500 text-sm">With Gaps</div>
            </div>
          </div>
        </div>
      </div>

      <div class="col-6 md:col-3">
        <div class="surface-card p-3 shadow-2 border-round">
          <div class="flex align-items-center gap-3">
            <div class="flex align-items-center justify-content-center border-round w-3rem h-3rem bg-red-100">
              <i class="pi pi-times-circle text-red-600 text-xl"></i>
            </div>
            <div>
              <div class="text-2xl font-bold text-red-600">{{ availabilityStore.offlineStations }}</div>
              <div class="text-500 text-sm">Offline</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Empty State -->
    <div v-if="!availabilityStore.selectedConnectionId" class="surface-card p-6 shadow-2 border-round text-center">
      <i class="pi pi-database text-5xl text-300 mb-3"></i>
      <p class="text-500 text-lg m-0">Select a network connection to view station availability</p>
    </div>

    <!-- Loading State -->
    <div v-else-if="availabilityStore.loadingSummary" class="surface-card p-6 shadow-2 border-round text-center">
      <ProgressSpinner style="width: 50px; height: 50px" strokeWidth="4"/>
      <p class="text-500 mt-3 m-0">Loading availability data...</p>
    </div>

    <!-- Heatmap Grid -->
    <div v-else class="surface-card shadow-2 border-round overflow-hidden">
      <!-- Hour Labels Header -->
      <div class="grid-header flex align-items-center surface-100 border-bottom-1 surface-border p-2">
        <div class="station-name-col font-medium text-600 text-sm pl-3">Station</div>
        <div class="hours-col flex gap-1">
          <span
              v-for="(label, index) in availabilityStore.hourLabels"
              :key="index"
              class="hour-label text-xs text-500 text-center"
          >
            {{ formatHourLabel(label) }}
          </span>
        </div>
        <div class="action-col"></div>
      </div>

      <!-- Station Rows -->
      <div class="stations-container" style="max-height: 65vh; overflow-y: auto;">
        <div
            v-for="station in availabilityStore.stations"
            :key="station.station_link_id"
            class="station-row flex align-items-center p-2 border-bottom-1 surface-border"
        >
          <!-- Station Name -->
          <div class="station-name-col">
            <div class="flex align-items-center gap-2">
              <Tag
                  :severity="availabilityStore.getStatusSeverity(station.status)"
                  :value="station.status"
                  class="text-xs"
                  style="min-width: 4.5rem"
              />
              <div>
                <div class="font-medium text-900 text-sm white-space-nowrap overflow-hidden text-overflow-ellipsis"
                     style="max-width: 120px;">
                  {{ station.station_name }}
                </div>
                <small class="text-400">~{{ station.expected_hourly }}/hr</small>
              </div>
            </div>
          </div>

          <!-- Hour Cells -->
          <div class="hours-col flex gap-1">
            <div
                v-for="(hourKey, index) in availabilityStore.hourKeys"
                :key="index"
                class="hour-cell border-round cursor-pointer transition-all transition-duration-150"
                :class="getCellClass(station, hourKey)"
                v-tooltip.top="getCellTooltip(station, hourKey, index)"
                @click="onCellClick(station, hourKey)"
            ></div>
          </div>

          <!-- Action -->
          <div class="action-col text-center">
            <Button
                icon="pi pi-arrow-right"
                text
                rounded
                size="small"
                v-tooltip.top="'View monthly detail'"
            />
          </div>
        </div>

        <!-- No Data -->
        <div v-if="availabilityStore.stations.length === 0" class="p-4 text-center">
          <i class="pi pi-inbox text-4xl text-300 mb-2"></i>
          <p class="text-500 m-0">No stations found for this connection</p>
        </div>
      </div>

      <!-- Legend -->
      <div class="flex align-items-center gap-4 p-3 surface-100 border-top-1 surface-border">
        <span class="text-500 text-sm">Legend:</span>
        <div class="flex align-items-center gap-2">
          <div class="legend-cell cell-full"></div>
          <span class="text-sm text-600">Normal</span>
        </div>
        <div class="flex align-items-center gap-2">
          <div class="legend-cell cell-partial"></div>
          <span class="text-sm text-600">Reduced</span>
        </div>
        <div class="flex align-items-center gap-2">
          <div class="legend-cell cell-empty"></div>
          <span class="text-sm text-600">No Data</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import {computed, onMounted, ref} from 'vue'
import {useAvailabilityStore} from '@/stores/dataAvailability'
import {fetchNetworkConnections} from '@/services/adlService'

import Button from 'primevue/button'
import Select from 'primevue/select'
import Tag from 'primevue/tag'
import ProgressSpinner from 'primevue/progressspinner'

const props = defineProps({
  apiUrl: {
    type: String,
    required: true
  }
})

const availabilityStore = useAvailabilityStore()
const connections = ref([])

// Computed
const formattedTimeRange = computed(() => {
  if (!availabilityStore.timeRangeStart) return ''

  const start = new Date(availabilityStore.timeRangeStart)
  const end = new Date(availabilityStore.timeRangeEnd)

  return `${start.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit'
  })} - ${end.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}`
})

// Methods
function formatHourLabel(label) {
  // label is like "14:00" - extract just the hour for compact display
  return label.split(':')[0]
}

function getCellClass(station, hourKey) {
  const status = availabilityStore.getCellStatus(station, hourKey)
  return `cell-${status}`
}

function getCellTooltip(station, hourKey, index) {
  const count = station.hourly_counts?.[hourKey] || 0
  const expected = station.expected_hourly || 0
  const label = availabilityStore.hourLabels[index] || hourKey

  return `${label} · ${count} records (expected ~${expected})`
}

function onCellClick(station, hourKey) {
  // Could open a dialog with parameter breakdown
  console.log(`Clicked ${station.station_name} at ${hourKey}`)
}

function onConnectionChange() {
  availabilityStore.loadSummary()
}


// Load connections on mount
onMounted(async () => {
  try {
    const response = await fetchNetworkConnections(availabilityStore.axios)
    connections.value = response.data

    // Auto-select first connection if available
    if (connections.value.length > 0 && !availabilityStore.selectedConnectionId) {
      availabilityStore.setSelectedConnection(connections.value[0].id)
    }
  } catch (err) {
    console.error('Failed to load connections:', err)
  }
})
</script>

<style scoped>
.availability-dashboard {
  font-family: var(--font-family);
}

/* Grid Layout */
.grid-header,
.station-row {
  display: grid;
  grid-template-columns: 200px 1fr 50px;
  gap: 1rem;
}

.station-name-col {
  min-width: 200px;
}

.hours-col {
  display: flex;
  gap: 3px;
  flex: 1;
}

.action-col {
  width: 50px;
}

/* Hour Labels */
.hour-label {
  width: 18px;
  flex-shrink: 0;
}

/* Hour Cells */
.hour-cell {
  width: 18px;
  height: 24px;
  flex-shrink: 0;
}

.hour-cell:hover {
  transform: scaleY(1.15);
  box-shadow: 0 0 8px rgba(34, 197, 94, 0.4);
}

/* Cell States */
.cell-full {
  background-color: #22c55e;
}

.cell-partial {
  background-color: #f59e0b;
}

.cell-low {
  background-color: #ef4444;
}

.cell-empty {
  background-color: #e5e7eb;
}

/* Legend */
.legend-cell {
  width: 14px;
  height: 14px;
  border-radius: 2px;
}

.legend-cell.cell-full {
  background-color: #22c55e;
}

.legend-cell.cell-partial {
  background-color: #f59e0b;
}

.legend-cell.cell-empty {
  background-color: #e5e7eb;
}

/* Scrollbar */
.stations-container::-webkit-scrollbar {
  width: 6px;
}

.stations-container::-webkit-scrollbar-track {
  background: #f3f4f6;
}

.stations-container::-webkit-scrollbar-thumb {
  background: #9ca3af;
  border-radius: 3px;
}

.stations-container::-webkit-scrollbar-thumb:hover {
  background: #6b7280;
}

/* Responsive */
@media (max-width: 768px) {
  .grid-header,
  .station-row {
    grid-template-columns: 140px 1fr 40px;
  }

  .station-name-col {
    min-width: 140px;
  }

  .hour-cell,
  .hour-label {
    width: 12px;
  }

  .hour-cell {
    height: 20px;
  }
}
</style>