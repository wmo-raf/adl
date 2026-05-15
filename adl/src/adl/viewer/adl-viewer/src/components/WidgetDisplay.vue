<script setup>
import {computed, onMounted, onUnmounted, ref} from "vue"
import {useWidgetStore} from "@/stores/widget.js"
import StationRotatingCards from "@/components/widget/StationRotatingCards.vue"
import StationMapOverlay from "@/components/widget/StationMapOverlay.vue"

const props = defineProps({
  apiUrl: {type: String, required: true},
  widgetName: {type: String, default: ''},
  stations: {type: String, default: '[]'},
  parameters: {type: String, default: '[]'},
  rotationInterval: {type: String, default: 10},
  pollInterval: {type: String, default: 5},
  defaultView: {type: String, default: 'rotating'},
  countryIso3: {type: String, default: ''},
  countryBounds: {type: String, default: ''},
  organisationName: {type: String, default: ''},
  logoUrl: {type: String, default: ''},
})

const store = useWidgetStore()

const isRotating = computed(() => store.activeView === 'rotating')
const hasFooter = computed(() => !!(props.organisationName || props.logoUrl))
const isFullscreen = ref(false)

function toggleView() {
  store.setView(isRotating.value ? 'map' : 'rotating')
}

function toggleFullscreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen()
  } else {
    document.exitFullscreen()
  }
}

function onFullscreenChange() {
  isFullscreen.value = !!document.fullscreenElement
}

onMounted(() => {
  const stations = JSON.parse(props.stations)
  const parameters = JSON.parse(props.parameters)
  store.init(stations, parameters, props.defaultView)
  store.startPolling(Number(props.pollInterval))
  document.addEventListener('fullscreenchange', onFullscreenChange)
})

onUnmounted(() => {
  document.removeEventListener('fullscreenchange', onFullscreenChange)
})
</script>

<template>
  <div class="widget-root" :class="{ 'has-footer': hasFooter }">
    <div class="top-controls">
      <button class="ctrl-btn" @click="toggleFullscreen" :title="isFullscreen ? 'Exit Fullscreen' : 'Enter Fullscreen'">
        <i :class="isFullscreen ? 'fa-solid fa-compress' : 'fa-solid fa-expand'"></i>
      </button>
      <button class="ctrl-btn" @click="toggleView" :title="isRotating ? 'Switch to Map View' : 'Switch to Card View'">
        <i :class="isRotating ? 'fa-solid fa-map' : 'fa-solid fa-table-cells'"></i>
      </button>
    </div>

    <div class="widget-body">
      <StationRotatingCards
          v-if="isRotating"
          :rotation-interval="Number(rotationInterval)"
          :country-iso3="countryIso3"
      />
      <StationMapOverlay
          v-else
          :country-iso3="countryIso3"
          :country-bounds="countryBounds"
          :rotation-interval="Number(rotationInterval)"
      />
    </div>

    <footer v-if="hasFooter" class="widget-footer">
      <img v-if="logoUrl" :src="logoUrl" class="footer-logo" alt="Organisation logo"/>
      <span v-if="organisationName" class="footer-name">{{ organisationName }}</span>
    </footer>
  </div>
</template>

<style scoped>
.widget-root {
  width: 100%;
  height: 100%;
  position: relative;
  background: #0f172a;
  color: #f1f5f9;
  font-family: system-ui, -apple-system, sans-serif;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.widget-body {
  flex: 1;
  min-height: 0;
  position: relative;
}

.top-controls {
  position: absolute;
  top: 1rem;
  right: 1rem;
  z-index: 100;
  display: flex;
  gap: 0.5rem;
}

.ctrl-btn {
  background: rgba(255, 255, 255, 0.12);
  color: #f1f5f9;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  width: 2.2rem;
  height: 2.2rem;
  font-size: 0.9rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s;
}

.ctrl-btn:hover {
  background: rgba(255, 255, 255, 0.22);
}

.widget-footer {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1.25rem;
  padding: 0.75rem 2rem;
  background: rgba(255, 255, 255, 0.04);
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.footer-logo {
  height: clamp(2rem, 4vh, 3.5rem);
  width: auto;
  object-fit: contain;
  opacity: 0.85;
}

.footer-name {
  font-size: clamp(1rem, 2vw, 1.6rem);
  font-weight: 600;
  color: #cbd5e1;
  letter-spacing: 0.03em;
  white-space: nowrap;
}
</style>
