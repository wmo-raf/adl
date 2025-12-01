<template>
  <div class="qc-dashboard surface-ground min-h-screen p-4">

    <div class="surface-card p-4 shadow-2 border-round mb-4">
      <div class="flex flex-column md:flex-row justify-content-between align-items-center gap-3">
        <div>
          <h1 class="text-2xl font-bold m-0 text-900">QC Network Health</h1>
          <p class="text-500 m-0 mt-1">
            Overview for {{ displayDate }}
          </p>
        </div>

        <div class="flex align-items-center gap-2">
          <DatePicker
              v-model="qcStore.selectedDate"
              view="month"
              dateFormat="M yy"
              showIcon
              class="w-12rem"
              @date-select="(val) => qcStore.setSelectedDate(val)"
          />

          <Button
              icon="pi pi-refresh"
              rounded
              outlined
              @click="qcStore.loadQCSummary"
              :loading="qcStore.loadingSummary"
              aria-label="Refresh"
          />
        </div>
      </div>
    </div>

    <div class="surface-card shadow-2 border-round overflow-hidden">
      <DataTable
          :value="qcStore.stationSummaries"
          :loading="qcStore.loadingSummary"
          rowGroupMode="subheader"
          groupRowsBy="connection_name"
          sortField="fail_pct"
          :sortOrder="-1"
          scrollable
          scrollHeight="600px"
          sortMode="single"
          expandableRowGroups
          v-model:expandedRowGroups="expandedRowGroups"
          tableStyle="min-width: 50rem"
      >

        <template #empty>
          <div class="text-center p-4">
            <i class="pi pi-database text-4xl text-500 mb-2"></i>
            <p class="text-500">No QC data found for this month.</p>
          </div>
        </template>

        <template #groupheader="slotProps">
          <div class="flex align-items-center gap-2 py-2 px-3 cursor-pointer font-bold text-800">
            <i class="pi pi-server text-primary"></i>
            <span class="vertical-align-middle">{{ slotProps.data.connection_name }}</span>
            <Badge :value="getGroupCount(slotProps.data.connection_name)" severity="secondary" class="ml-2"/>
          </div>
        </template>

        <Column field="station_name" header="Station" sortable style="width: 25%">
          <template #body="{ data }">
            <div class="font-medium text-900">{{ data.station_name }}</div>
            <small class="text-500">ID: {{ data.station_id }}</small>
          </template>
        </Column>

        <Column field="record_count" header="Records" sortable style="width: 15%">
          <template #body="{ data }">
            <div class="flex align-items-center gap-2">
              <span>{{ data.record_count.toLocaleString() }}</span>
            </div>
          </template>
        </Column>

        <Column field="fail_pct" header="Data Quality Profile" sortable style="width: 40%">
          <template #body="{ data }">
            <div class="w-full" v-if="data.record_count > 0">
              <div class="flex justify-content-between text-xs mb-1">
                <span class="text-green-600 font-medium">{{ data.pass_pct }}% Good</span>
                <div class="flex gap-3">
                  <span v-if="data.not_evaluated_pct > 0" class="text-gray-500">{{ data.not_evaluated_pct }}% N/A</span>
                  <span v-if="data.suspect_pct > 0" class="text-yellow-600">{{ data.suspect_pct }}% Suspect</span>
                  <span v-if="data.fail_pct > 0" class="text-red-600 font-bold">{{ data.fail_pct }}% Fail</span>
                </div>
              </div>

              <div class="flex h-1rem border-round overflow-hidden surface-200 w-full relative"
                   v-tooltip.top="getTooltip(data)">
                <div class="bg-green-500 h-full transition-all transition-duration-500"
                     :style="{ width: data.pass_pct + '%' }"></div>
                <div class="bg-gray-400 h-full transition-all transition-duration-500"
                     :style="{ width: data.not_evaluated_pct + '%' }"></div>
                <div class="bg-yellow-500 h-full transition-all transition-duration-500"
                     :style="{ width: data.suspect_pct + '%' }"></div>
                <div class="bg-red-500 h-full transition-all transition-duration-500"
                     :style="{ width: data.fail_pct + '%' }"></div>
              </div>
            </div>
            <div v-else class="text-500 text-sm font-italic">No records</div>
          </template>
        </Column>
      </DataTable>
    </div>
  </div>
</template>

<script setup>
import {computed, onMounted, ref, watch} from 'vue'
import {useQCStore} from '@/stores/qc'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import DatePicker from 'primevue/datepicker'
import Badge from 'primevue/badge'

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

const qcStore = useQCStore()
const expandedRowGroups = ref([])

// Helper to show nice date in header
const displayDate = computed(() => {
  if (!qcStore.apiMonth || !qcStore.apiYear) return '...'
  const date = new Date(qcStore.apiYear, qcStore.apiMonth - 1)
  return date.toLocaleDateString(undefined, {month: 'long', year: 'numeric'})
})

// Helper to count stations per group for the header badge
const getGroupCount = (connectionName) => {
  return qcStore.stationSummaries.filter(s => s.connection_name === connectionName).length
}

// Tooltip text for the health bar
const getTooltip = (data) => {
  return `Pass: ${data.pass_count} | Not Evaluated: ${data.not_evaluated_count} | Suspect: ${data.suspect_count} | Fail: ${data.fail_count}`
}

onMounted(async () => {
  await qcStore.loadQCSummary()

  // Auto-expand all groups initially
  const uniqueConnections = [...new Set(qcStore.stationSummaries.map(s => s.connection_name))]
  expandedRowGroups.value = uniqueConnections
})

// Watch for data changes and update expanded groups
watch(
    () => qcStore.stationSummaries,
    (newSummaries) => {
      if (newSummaries.length > 0) {
        const uniqueConnections = [...new Set(newSummaries.map(s => s.connection_name))]
        expandedRowGroups.value = uniqueConnections
      }
    }
)

</script>

<style scoped>
.qc-dashboard {
  font-family: var(--font-family);
}

/* Custom transition for health bars growing */
.transition-all {
  transition-property: all;
}

.transition-duration-500 {
  transition-duration: 500ms;
}
</style>