<template>
  <div class="active-tasks-dashboard">
    <!-- Header with Network Filter -->
    <div class="card mb-4">
      <div class="flex justify-content-between align-items-center p-3">
        <h2 class="m-0">Active Tasks Monitor</h2>
        <div class="flex gap-3 align-items-center">
          <Select
              v-model="selectedNetworkId"
              :options="networkConnections"
              optionLabel="name"
              optionValue="id"
              placeholder="Filter by Network"
              showClear
              class="w-full md:w-20rem"
              @change="fetchActiveTasks"
          >
            <template #value="slotProps">
              <div v-if="slotProps.value">
                <i class="pi pi-filter mr-2"></i>
                {{ getNetworkName(slotProps.value) }}
              </div>
              <span v-else>
                <i class="pi pi-filter mr-2"></i>
                All Networks
              </span>
            </template>
          </Select>

          <Button
              label="Refresh"
              icon="pi pi-refresh"
              @click="fetchActiveTasks"
              :loading="loading"
              severity="secondary"
          />
        </div>
      </div>
    </div>

    <!-- Loading State -->
    <div v-if="loading && activeTasks.length === 0" class="card p-4 text-center">
      <ProgressSpinner/>
      <p class="mt-3 text-gray-600">Loading active tasks...</p>
    </div>

    <!-- Error State -->
    <Message v-else-if="error" severity="error" :closable="false" class="mb-3">
      {{ error }}
    </Message>

    <!-- No Tasks State -->
    <div v-else-if="!loading && activeTasks.length === 0" class="card p-5 text-center">
      <i class="pi pi-inbox text-6xl text-gray-400 mb-3"></i>
      <h3 class="text-gray-600">No Active Tasks</h3>
      <p class="text-gray-500">
        {{ selectedNetworkId ? 'No tasks running for this network connection' : 'No tasks are currently running' }}
      </p>
    </div>

    <!-- Active Tasks List -->
    <div v-else class="tasks-list">
      <Accordion
        v-model:value="expandedPanels"
        :multiple="true"
        expandIcon="pi pi-chevron-down"
        collapseIcon="pi pi-chevron-up"
      >
        <AccordionPanel
            v-for="(task, index) in activeTasks"
            :key="task.task_id"
            :value="task.task_id"
        >
          <AccordionHeader>
            <div class="flex align-items-center justify-content-between w-full pr-3">
              <div class="flex align-items-center gap-3">
                <i class="pi pi-cog task-spinner" :class="{ 'spinning': task.status === 'STARTED' }"></i>
                <div>
                  <div class="font-semibold">{{ task.task_name_short }}</div>
                  <div class="text-sm text-gray-500">
                    Network ID: {{ task.network_id }} • {{ task.task_id.slice(0, 8) }}...
                  </div>
                </div>
              </div>

              <div class="flex align-items-center gap-3">
                <Badge
                    :value="task.status"
                    :severity="getStatusSeverity(task.status)"
                />
                <small class="text-gray-500">
                  {{ formatTime(task.started_at) }}
                </small>
              </div>
            </div>
          </AccordionHeader>

          <AccordionContent>
            <!-- Task Log Viewer -->
            <TaskLogViewer
                :task-id="task.task_id"
                :title="`Task Logs - ${task.task_name_short}`"
            />
          </AccordionContent>
        </AccordionPanel>
      </Accordion>
    </div>

    <!-- Auto-refresh indicator -->
    <div v-if="autoRefresh && refreshTimer" class="mt-3 text-center">
      <small class="text-gray-500">
        <i class="pi pi-sync spinning"></i>
        Auto-refreshing every {{ Math.round(refreshInterval / 1000) }}s
      </small>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, computed } from 'vue'
import TaskLogViewer from './TaskLogViewer.vue'
import Accordion from 'primevue/accordion'
import AccordionPanel from 'primevue/accordionpanel'
import AccordionHeader from 'primevue/accordionheader'
import AccordionContent from 'primevue/accordioncontent'
import Select from 'primevue/select'
import Button from 'primevue/button'
import Badge from 'primevue/badge'
import Message from 'primevue/message'
import ProgressSpinner from 'primevue/progressspinner'

const props = defineProps({
  autoRefresh: {
    type: Boolean,
    default: false
  },
  refreshInterval: {
    type: Number,
    default: 60000  // 1 minute
  }
})

const activeTasks = ref([])
const networkConnections = ref([])
const selectedNetworkId = ref(null)
const loading = ref(false)
const error = ref(null)
const expandedPanels = ref([]) // Tracks expanded panels by task_id
const refreshTimer = ref(null)

const getNetworkName = (id) => {
  const network = networkConnections.value.find(n => n.id === id)
  return network ? network.name : `Network ${id}`
}

const formatTime = (timestamp) => {
  if (!timestamp) return 'Just now'
  const date = new Date(timestamp)
  const now = new Date()
  const diffMs = now - date
  const diffMins = Math.floor(diffMs / 60000)

  if (diffMins < 1) return 'Just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`

  return date.toLocaleTimeString()
}

const getStatusSeverity = (status) => {
  const severityMap = {
    'STARTED': 'success',
    'PENDING': 'info',
    'RETRY': 'warning',
    'FAILURE': 'danger',
    'SUCCESS': 'success'
  }
  return severityMap[status] || 'secondary'
}

const fetchActiveTasks = async () => {
  loading.value = true
  error.value = null

  try {
    const url = selectedNetworkId.value
        ? `/tasks/active/network/${selectedNetworkId.value}/`
        : '/tasks/active/'

    const response = await fetch(url)

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }

    const data = await response.json()

    // Keep track of which tasks were expanded before refresh
    const previouslyExpanded = expandedPanels.value.slice()

    activeTasks.value = data.tasks

    // Preserve expanded panels if they still exist
    if (previouslyExpanded.length > 0) {
      const existingTaskIds = activeTasks.value.map(task => task.task_id)
      expandedPanels.value = previouslyExpanded.filter(taskId =>
        existingTaskIds.includes(taskId)
      )
    } else if (activeTasks.value.length > 0 && expandedPanels.value.length === 0) {
      // Auto-expand first task on initial load
      expandedPanels.value = [activeTasks.value[0].task_id]
    }

  } catch (err) {
    console.error('Error fetching active tasks:', err)
    error.value = `Failed to fetch active tasks: ${err.message}`
  } finally {
    loading.value = false
  }
}

const fetchNetworkConnections = async () => {
  try {
    const response = await fetch('/api/network-connection/')
    networkConnections.value = await response.json()
  } catch (err) {
    console.error('Error fetching network connections:', err)
  }
}

const startAutoRefresh = () => {
  if (props.autoRefresh) {
    refreshTimer.value = setInterval(fetchActiveTasks, props.refreshInterval)
  }
}

const stopAutoRefresh = () => {
  if (refreshTimer.value) {
    clearInterval(refreshTimer.value)
    refreshTimer.value = null
  }
}

onMounted(() => {
  fetchNetworkConnections()
  fetchActiveTasks()
  startAutoRefresh()
})

onUnmounted(() => {
  stopAutoRefresh()
})
</script>

<style scoped>
.active-tasks-dashboard {
}

.tasks-list {
  /* Spacing handled by Accordion */
}

.task-spinner {
  transition: transform 0.3s ease;
}

.spinning {
  animation: spin 2s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* Custom accordion styling */
:deep(.p-accordionheader) {
  transition: all 0.2s;
}

:deep(.p-accordionheader:hover) {
  background: var(--surface-hover);
}

:deep(.p-accordioncontent) {
  padding: 1rem;
  background: var(--surface-ground);
}
</style>