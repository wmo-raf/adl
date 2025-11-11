import {onUnmounted, ref, watch} from 'vue'

export function useTaskStream(taskId, options = {}) {
    const {
        maxLogs = 1000,
        autoConnect = true
    } = options

    const eventSource = ref(null)
    const logs = ref([])
    const isConnected = ref(false)
    const error = ref(null)

    const connect = (id) => {
        if (!id) {
            console.warn('No task ID provided')
            return
        }

        disconnect()
        logs.value = []
        error.value = null

        // django-eventstream URL format
        const sseUrl = `/events/?channel=task-${id}`

        console.log(`Connecting to SSE: ${sseUrl}`)

        try {
            eventSource.value = new ReconnectingEventSource(sseUrl)

            // Handle stream open
            eventSource.value.addEventListener('stream-open', () => {
                console.log('✅ SSE connected to task:', id)
                isConnected.value = true
                error.value = null
            })

            eventSource.value.onmessage = (event) => {
                console.log('📬 Generic message event:', event)
            }

            // Handle stream reset (reconnection)
            eventSource.value.addEventListener('stream-reset', () => {
                console.log('🔄 SSE stream reset')
                logs.value = []
            })

            // Listen for 'log' events
            eventSource.value.addEventListener('log', (event) => {
                try {
                    const data = JSON.parse(event.data)

                    logs.value.push({
                        message: data.message,
                        level: data.level,
                        timestamp: data.timestamp,
                        id: `${data.timestamp}-${logs.value.length}`
                    })

                    // Trim old logs to prevent memory issues
                    if (logs.value.length > maxLogs) {
                        const removeCount = logs.value.length - maxLogs
                        logs.value.splice(0, removeCount)
                    }
                } catch (err) {
                    console.error('Error parsing log event:', err)
                }
            })

            eventSource.value.onerror = (err) => {
                console.error('❌ SSE error:', err)

                // EventSource automatically reconnects, but we track the state
                if (eventSource.value?.readyState === EventSource.CLOSED) {
                    error.value = 'Stream connection closed'
                    isConnected.value = false
                }
            }
        } catch (err) {
            console.error('Failed to create SSE:', err)
            error.value = 'Failed to establish SSE connection'
        }
    }

    const disconnect = () => {
        if (eventSource.value) {
            console.log('Disconnecting SSE')
            eventSource.value.close()
            eventSource.value = null
        }
        isConnected.value = false
    }

    const clearLogs = () => {
        logs.value = []
    }

    // Auto-connect when taskId changes
    if (autoConnect) {
        watch(() => taskId.value, (newId) => {
            if (newId) {
                connect(newId)
            } else {
                disconnect()
            }
        }, {immediate: true})
    }

    onUnmounted(() => {
        disconnect()
    })

    return {
        logs,
        isConnected,
        error,
        connect,
        disconnect,
        clearLogs
    }
}