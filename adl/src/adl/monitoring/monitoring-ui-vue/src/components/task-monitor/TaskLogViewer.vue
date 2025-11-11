<template>
  <Card class="task-log-viewer">
    <template #content>
      <div class="flex justify-content-between align-items-center mb-3">
        <div class="flex align-items-center gap-2">
          <i :class="isConnected ? 'pi pi-circle-fill text-green-500' : 'pi pi-circle text-gray-400'"
             style="font-size: 0.75rem"></i>
          <span class="font-medium">{{ isConnected ? 'Connected' : 'Disconnected' }}</span>
        </div>
        <div class="flex gap-2">
          <Button
            icon="pi pi-trash"
            severity="secondary"
            text
            rounded
            size="small"
            @click="clearLogs"
            v-tooltip.top="'Clear logs'"
          />
          <Button
            :icon="autoScroll ? 'pi pi-lock' : 'pi pi-lock-open'"
            severity="secondary"
            text
            rounded
            size="small"
            @click="autoScroll = !autoScroll"
            v-tooltip.top="autoScroll ? 'Auto-scroll enabled' : 'Auto-scroll disabled'"
          />
        </div>
      </div>

      <div v-if="error" class="mb-3">
        <Message severity="error" :closable="false">{{ error }}</Message>
      </div>

      <div
        ref="logsContainer"
        class="logs-container"
        :class="{ 'has-logs': logs.length > 0 }"
      >
        <div v-if="logs.length === 0" class="no-logs">
          <ProgressSpinner style="width: 50px; height: 50px" strokeWidth="4" />
          <p class="text-gray-500 mt-3">Waiting for logs...</p>
        </div>

        <div
          v-for="log in logs"
          :key="log.id"
          :class="['log-entry', `log-${log.level}`]"
        >
          <span class="log-timestamp">{{ formatTime(log.timestamp) }}</span>
          <span class="log-message">{{ log.message }}</span>
        </div>
      </div>

      <div class="log-stats mt-3 flex justify-content-between align-items-center">
        <div class="flex gap-3">
          <Tag :value="`${logs.length} logs`" severity="info" />
          <Tag
            v-if="errorCount > 0"
            :value="`${errorCount} errors`"
            severity="danger"
          />
          <Tag
            v-if="warningCount > 0"
            :value="`${warningCount} warnings`"
            severity="warning"
          />
        </div>
      </div>
    </template>
  </Card>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { useTaskStream } from '@/composables/useTaskStream'
import Card from 'primevue/card'
import Button from 'primevue/button'
import Message from 'primevue/message'
import Tag from 'primevue/tag'
import ProgressSpinner from 'primevue/progressspinner'

const props = defineProps({
  taskId: {
    type: String,
    required: true
  },
  title: {
    type: String,
    default: 'Task Logs'
  }
})

const logsContainer = ref(null)
const autoScroll = ref(true)

const { logs, isConnected, error, clearLogs: clearLogsInternal } = useTaskStream(
  computed(() => props.taskId)
)

const errorCount = computed(() => logs.value.filter(log => log.level === 'error').length)
const warningCount = computed(() => logs.value.filter(log => log.level === 'warning').length)

const formatTime = (timestamp) => {
  if (!timestamp) return ''
  return new Date(timestamp).toLocaleTimeString()
}

const scrollToBottom = () => {
  if (autoScroll.value && logsContainer.value) {
    nextTick(() => {
      logsContainer.value.scrollTop = logsContainer.value.scrollHeight
    })
  }
}

const clearLogs = () => {
  clearLogsInternal()
}

watch(() => logs.value.length, () => {
  scrollToBottom()
})
</script>

<style scoped>
.task-log-viewer {
  height: 100%;
}

.logs-container {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 1rem;
  border-radius: 6px;
  height: 400px;
  overflow-y: auto;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
}

.logs-container.has-logs {
  padding: 0.5rem;
}

.no-logs {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.log-entry {
  padding: 0.25rem 0.5rem;
  margin: 0.125rem 0;
  border-radius: 3px;
  transition: background-color 0.15s;
}

.log-entry:hover {
  background: rgba(255, 255, 255, 0.05);
}

.log-timestamp {
  color: #858585;
  margin-right: 0.75rem;
  font-size: 0.85em;
  user-select: none;
}

.log-message {
  word-break: break-word;
}

/* Log level colors */
.log-info .log-message { color: #4ec9b0; }
.log-debug .log-message { color: #9cdcfe; }
.log-warning .log-message { color: #dcdcaa; }
.log-error .log-message { color: #f48771; }
.log-success .log-message { color: #6a9955; }

.log-stats {
  border-top: 1px solid var(--surface-border);
  padding-top: 0.75rem;
}

/* Custom scrollbar */
.logs-container::-webkit-scrollbar {
  width: 8px;
}

.logs-container::-webkit-scrollbar-track {
  background: #2d2d2d;
  border-radius: 4px;
}

.logs-container::-webkit-scrollbar-thumb {
  background: #555;
  border-radius: 4px;
}

.logs-container::-webkit-scrollbar-thumb:hover {
  background: #666;
}
</style>