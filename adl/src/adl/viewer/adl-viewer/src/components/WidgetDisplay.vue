<script setup>
import {computed, onMounted} from "vue"
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
})

const store = useWidgetStore()

const isRotating = computed(() => store.activeView === 'rotating')

function toggleView() {
  store.setView(isRotating.value ? 'map' : 'rotating')
}

onMounted(() => {
  const stations = JSON.parse(props.stations)
  const parameters = JSON.parse(props.parameters)
  store.init(stations, parameters, props.defaultView)
  store.startPolling(Number(props.pollInterval))
})
</script>

<template>
  <div class="widget-root">
    <button class="view-toggle" @click="toggleView" :title="isRotating ? 'Switch to Map View' : 'Switch to Card View'">
      {{ isRotating ? 'Map' : 'Cards' }}
    </button>

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
}

.view-toggle {
  position: absolute;
  top: 1rem;
  right: 1rem;
  z-index: 100;
  background: rgba(255, 255, 255, 0.12);
  color: #f1f5f9;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  padding: 0.4rem 0.9rem;
  font-size: 0.85rem;
  cursor: pointer;
  transition: background 0.2s;
}

.view-toggle:hover {
  background: rgba(255, 255, 255, 0.22);
}
</style>
