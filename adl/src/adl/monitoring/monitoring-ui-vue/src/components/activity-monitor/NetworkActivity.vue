<script setup>
import {computed, onMounted, ref} from "vue"

import DataTable from "primevue/datatable"
import Column from "primevue/column"
import InputText from "primevue/inputtext"
import Button from "primevue/button"

const props = defineProps({
  connectionId: {
    type: Number,
    required: true
  }
})

const loading = ref(false)
const stations = ref([])
// Initialize with defaults
const summary = ref({active: 0, warning: 0, error: 0})
const connection = ref(null)

const search = ref("")
const filter = ref("all")

const fetchData = async () => {
  loading.value = true
  try {
    const res = await fetch(`/monitoring/connection-activity/${props.connectionId}/`)
    if (!res.ok) throw new Error("API not found")
    const data = await res.json()
    connection.value = data.connection
    summary.value = data.summary
    stations.value = data.stations
  } catch (err) {
    console.error("Failed to load activity data:", err)
  }
  loading.value = false
}

onMounted(fetchData)

const formatDate = (isoString) => {
  if (!isoString) return ''
  try {
    const date = new Date(isoString)
    return new Intl.DateTimeFormat('default', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    }).format(date)
  } catch (e) {
    return isoString
  }
}

// Map backend 'error' to frontend 'danger' class, etc.
const getSeverityClass = (status) => {
  const map = {
    active: "success",
    warning: "warning",
    error: "danger"
  }
  return map[status] || "info"
}

const filteredStations = computed(() => {
  let list = stations.value || []

  // --- Updated Filter Logic for Dual Status ---
  if (filter.value !== "all") {
    list = list.filter((s) => {
      const pipe = s.pipeline_status
      const data = s.data_status

      if (filter.value === 'active') {
        // Strict: Both must be healthy to be considered fully active
        return pipe === 'active' && data === 'active'
      }
      if (filter.value === 'warning') {
        // Loose: If either is warning (and neither is error), show in warning
        return (pipe === 'warning' || data === 'warning')
      }
      if (filter.value === 'error') {
        // Critical: If either is broken, show in error
        return pipe === 'error' || data === 'error'
      }
      return true
    })
  }

  if (search.value.trim().length > 0) {
    const q = search.value.toLowerCase()
    list = list.filter((s) =>
        s.name.toLowerCase().includes(q)
    )
  }

  return list
})
</script>

<template>
  <div class="station-monitor-container">
    <div class="header-section">
      <div class="header-top-row">
        <div class="header-title-group">
          <h1 class="connection-name">{{ connection?.name || 'Station Monitor' }}</h1>
          <div class="header-badges">
                <span class="meta-badge" v-if="connection?.enabled">
                    <i class="pi pi-check-circle" style="color: #16a34a"></i> Enabled
                </span>
            <span class="meta-badge">
                    <i class="pi pi-clock"></i> {{ connection?.interval_minutes || 5 }}m Interval
                </span>
            <span class="meta-badge">
                    <i class="pi pi-box"></i> {{ connection?.plugin || 'Plugin' }}
                </span>
          </div>
        </div>

        <div class="status-summary-group">
          <div class="summary-card success">
            <span class="summary-label">Active</span>
            <span class="summary-count">{{ summary?.active || 0 }}</span>
          </div>

          <div class="summary-card warning">
            <span class="summary-label">Warning</span>
            <span class="summary-count">{{ summary?.warning || 0 }}</span>
          </div>

          <div class="summary-card danger">
            <span class="summary-label">Error</span>
            <span class="summary-count">{{ summary?.error || 0 }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="content-section">
      <div class="controls-bar">
        <div class="controls-left">
          <div class="search-wrapper">
            <i class="pi pi-search search-icon"></i>
            <InputText
                v-model="search"
                placeholder="Search stations..."
                class="search-input"
            />
          </div>

          <div class="filter-group">
            <button
                :class="['filter-btn', { active: filter === 'all' }]"
                @click="filter = 'all'"
            >
              All
            </button>
            <button
                :class="['filter-btn success', { active: filter === 'active' }]"
                @click="filter = 'active'"
            >
              Healthy
            </button>
            <button
                :class="['filter-btn warning', { active: filter === 'warning' }]"
                @click="filter = 'warning'"
            >
              Warning
            </button>
            <button
                :class="['filter-btn danger', { active: filter === 'error' }]"
                @click="filter = 'error'"
            >
              Error
            </button>
          </div>
        </div>

        <Button
            icon="pi pi-refresh"
            label="Refresh"
            class="refresh-btn"
            :loading="loading"
            @click="fetchData"
        />
      </div>

      <div class="table-wrapper">
        <DataTable
            :value="filteredStations"
            :loading="loading"
            class="flat-table"
            paginator :rows="50"
        >
          <Column header="Station Name" style="min-width: 250px">
            <template #body="{ data }">
              <div class="station-cell">
                <div class="station-icon-box">
                  <i class="pi pi-map-marker"></i>
                </div>
                <div>
                  <a :href="`${data.logs_url}`" target="_blank" class="cell-title station-link">{{ data.name }}</a>
                </div>
              </div>
            </template>
          </Column>

          <Column header="Health" style="width: 140px; text-align: center">
            <template #body="{ data }">
              <div class="dual-status-wrapper">

                <div
                    :class="['status-indicator', getSeverityClass(data.pipeline_status)]"
                    :title="`Pipeline: ${data.pipeline_status}`"
                >
                  <i class="pi pi-server"></i>
                </div>

                <div
                    :class="['status-indicator', getSeverityClass(data.data_status)]"
                    :title="`Data Freshness: ${data.data_status}`"
                >
                  <i class="pi pi-database"></i>
                </div>

              </div>
            </template>
          </Column>

          <Column header="Last Check" style="width: 180px">
            <template #body="{ data }">
              <div class="time-cell">
                <span class="time-main" :class="{'text-danger': data.pipeline_status === 'error'}">
                    {{ data.last_check_human || 'Never' }}
                </span>
                <span class="time-sub" v-if="data.last_check">
                  {{ formatDate(data.last_check) }}
                </span>
              </div>
            </template>
          </Column>

          <Column header="Last Data (Obs)" style="width: 180px">
            <template #body="{ data }">
              <div class="time-cell">
                <span class="time-main" :class="{'text-danger': data.data_status === 'error'}">
                    {{ data.last_collected_human || 'Never' }}
                </span>
                <span class="time-sub" v-if="data.last_collected">
                  {{ formatDate(data.last_collected) }}
                </span>
              </div>
            </template>
          </Column>

          <Column header="Actions" style="width: 160px" alignFrozen="right">
            <template #body="{ data }">
              <div class="action-group">
                <a :href="`${data.data_viewer_url}`" target="_blank" class="action-link" title="View Data">
                  View Data
                </a>
                <span class="divider">|</span>
                <a :href="`${data.logs_url}`" target="_blank" class="action-link" title="View Logs">
                  Logs
                </a>
              </div>
            </template>
          </Column>

          <template #empty>
            <div class="empty-state">
              <i class="pi pi-search" style="font-size: 2rem; color: #94a3b8; margin-bottom: 1rem;"></i>
              <p>No stations match your criteria.</p>
            </div>
          </template>
        </DataTable>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* RESET & BASE */
.station-monitor-container {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  color: #334155;
  width: 100%;
  overflow: hidden;
}

/* HEADER */
.header-section {
  padding: 24px 32px;
  background-color: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}

.header-top-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 24px;
}

.connection-name {
  font-size: 24px;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 12px 0;
  line-height: 1.2;
}

.header-badges {
  display: flex;
  gap: 12px;
}

.meta-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  color: #64748b;
  background: #ffffff;
  padding: 4px 10px;
  border-radius: 4px;
  border: 1px solid #e2e8f0;
}

/* SUMMARY CARDS */
.status-summary-group {
  display: flex;
  gap: 12px;
}

.summary-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-width: 90px;
  padding: 8px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #fff;
}

.summary-label {
  font-size: 11px;
  text-transform: uppercase;
  font-weight: 600;
  color: #64748b;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}

.summary-count {
  font-size: 20px;
  font-weight: 700;
  line-height: 1;
}

/* Specific Summary Colors */
.summary-card.success .summary-count {
  color: #15803d;
}

.summary-card.success {
  border-bottom: 3px solid #15803d;
}

.summary-card.warning .summary-count {
  color: #b45309;
}

.summary-card.warning {
  border-bottom: 3px solid #b45309;
}

.summary-card.danger .summary-count {
  color: #b91c1c;
}

.summary-card.danger {
  border-bottom: 3px solid #b91c1c;
}


/* CONTROLS BAR */
.content-section {
  padding: 24px 32px;
  background: #ffffff;
}

.controls-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 16px;
}

.controls-left {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  align-items: center;
}

/* SEARCH INPUT */
.search-wrapper {
  position: relative;
}

.search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: #64748b;
  pointer-events: none;
}

.search-input {
  padding-left: 36px !important;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  height: 40px;
  width: 260px;
  color: #0f172a;
  font-size: 14px;
  background: #fff;
}

.search-input:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 1px #2563eb;
}

/* FILTER BUTTONS */
.filter-group {
  display: flex;
  background: #fff;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  overflow: hidden;
}

.filter-btn {
  background: #fff;
  border: none;
  padding: 0 16px;
  height: 38px;
  font-size: 13px;
  font-weight: 500;
  color: #64748b;
  border-right: 1px solid #e2e8f0;
  cursor: pointer;
  transition: all 0.1s;
}

.filter-btn:last-child {
  border-right: none;
}

.filter-btn:hover {
  background: #f8fafc;
  color: #0f172a;
}

.filter-btn.active {
  background: #0f172a;
  color: #ffffff;
}

/* Active states for filters */
.filter-btn.success.active {
  background: #166534;
}

.filter-btn.warning.active {
  background: #d97706;
}

.filter-btn.danger.active {
  background: #dc2626;
}

/* REFRESH BUTTON */
.refresh-btn {
  border: 1px solid #cbd5e1 !important;
  font-weight: 600 !important;
  font-size: 13px !important;
  height: 30px;
}

/* TABLE STYLES */
.table-wrapper {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  overflow: hidden;
}

:deep(.p-datatable-thead > tr > th) {
  background: #f1f5f9 !important;
  color: #475569 !important;
  font-weight: 600 !important;
  text-transform: uppercase !important;
  font-size: 12px !important;
  letter-spacing: 0.05em !important;
  padding: 16px 24px !important;
  border-bottom: 1px solid #e2e8f0 !important;
  border-top: none !important;
}

:deep(.p-datatable-tbody > tr > td) {
  padding: 16px 24px !important;
  border-bottom: 1px solid #f1f5f9 !important;
  color: #334155;
  font-size: 14px;
}

:deep(.p-datatable-tbody > tr:last-child > td) {
  border-bottom: none !important;
}

/* STATION CELL */
.station-cell {
  display: flex;
  align-items: center;
  gap: 12px;
}

.station-icon-box {
  width: 36px;
  height: 36px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
}

.cell-title {
  font-weight: 600;
  font-size: 14px;
  text-decoration: none;
}

.station-link:hover {
  text-decoration: underline;
}

/* NEW DUAL STATUS STYLES */
.dual-status-wrapper {
  display: flex;
  gap: 8px;
}

.status-indicator {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  transition: transform 0.1s;
  cursor: help;
}

.status-indicator:hover {
  transform: scale(1.05);
}

/* Indicators Colors */
.status-indicator.success {
  background: #dcfce7;
  color: #15803d;
  border: 1px solid #bbf7d0;
}

.status-indicator.warning {
  background: #fef3c7;
  color: #b45309;
  border: 1px solid #fde68a;
}

.status-indicator.danger {
  background: #fee2e2;
  color: #b91c1c;
  border: 1px solid #fecaca;
}

.status-indicator.info {
  background: #f1f5f9;
  color: #64748b;
  border: 1px solid #e2e8f0;
}

/* TIME CELL */
.time-cell {
  display: flex;
  flex-direction: column;
}

.time-main {
  color: #0f172a;
  font-weight: 500;
}

.time-main.text-danger {
  color: #dc2626;
}

.time-sub {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 2px;
  font-family: 'SF Mono', 'Roboto Mono', monospace;
}

/* ACTIONS */
.action-group {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: flex-end;
}

.action-link {
  text-decoration: none;
  font-weight: 600;
  font-size: 12px;
  cursor: pointer;
  transition: color 0.1s;
}

.action-link:hover {
  text-decoration: underline;
}

/* EMPTY STATE */
.empty-state {
  padding: 40px;
  text-align: center;
  color: #64748b;
}

/* RESPONSIVE */
@media (max-width: 768px) {
  .header-top-row, .controls-left, .status-summary-group {
    flex-direction: column;
    align-items: stretch;
    width: 100%;
  }

  .summary-card, .filter-btn, .search-input {
    width: 100%;
  }
}
</style>