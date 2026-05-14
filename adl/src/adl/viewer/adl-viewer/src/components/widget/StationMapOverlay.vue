<script setup>
import {computed, onMounted, onUnmounted, ref, watch} from "vue"
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import {useWidgetStore} from "@/stores/widget.js"
import {addCountryBoundary} from '@/composables/useCountryBoundary.js'
import {renderParamIcon} from '@/utils/paramIcons.js'

const TOUR_DWELL_MS = 10_000   // 10 s per stop
const FLY_DURATION_MS = 3_000  // 3 s fly animation
const STATION_ZOOM = 9

const props = defineProps({
  countryIso3: {type: String, default: ''},
  countryBounds: {type: String, default: ''},
  rotationInterval: {type: Number, default: 10},
})

const store = useWidgetStore()
const mapContainer = ref(null)
let map = null
const markers = []
let paramTimer = null
let tourTimer = null

// -1 = country overview, 0..n-1 = station index in sortedStations
const tourStep = ref(-1)
const currentParamIndex = ref(0)

const currentParam = computed(() => store.parameters[currentParamIndex.value] || null)

// Sort stations clockwise from geographic north using bearing from centroid
const sortedStations = computed(() => {
  const valid = store.stations.filter(s => s.lon !== null && s.lat !== null)
  if (!valid.length) return []
  const centerLon = valid.reduce((s, st) => s + st.lon, 0) / valid.length
  const centerLat = valid.reduce((s, st) => s + st.lat, 0) / valid.length
  return [...valid].sort((a, b) => {
    // atan2(Δlon, Δlat) gives bearing from north, positive = clockwise east
    const bearingA = (Math.atan2(a.lon - centerLon, a.lat - centerLat) + 2 * Math.PI) % (2 * Math.PI)
    const bearingB = (Math.atan2(b.lon - centerLon, b.lat - centerLat) + 2 * Math.PI) % (2 * Math.PI)
    return bearingA - bearingB
  })
})

// ─── Marker helpers ──────────────────────────────────────────────────────────

function getStationLabel(station) {
  const stationRecords = store.latestData[station.id] || []
  const param = currentParam.value

  let paramHtml = ''
  if (param) {
    const rec = stationRecords.find(r => r.parameter_id === param.id)
    if (rec && rec.value !== null) {
      const icon = renderParamIcon(param)
      const val = Number(rec.value).toFixed(1)
      const time = rec.time ? new Date(rec.time).toLocaleString(undefined, {
        day: '2-digit', month: 'short',
        hour: '2-digit', minute: '2-digit',
        hour12: false,
      }) : null

      paramHtml = `
        <div class="ol-param-row">
          <span class="ol-param-icon">${icon}</span>
          <span class="ol-param-value">${val}</span>
          <span class="ol-param-unit">${param.unit}</span>
        </div>
        ${time ? `<div class="ol-param-time">${time}</div>` : ''}
      `
    }
  }

  return `<div class="ol-marker">
    <div class="ol-station-name">${station.name}</div>
    ${paramHtml}
  </div>`
}

function buildMarkers() {
  markers.forEach(m => m.remove())
  markers.length = 0
  for (const station of store.stations) {
    if (station.lon === null || station.lat === null) continue
    const el = document.createElement('div')
    el.innerHTML = getStationLabel(station)
    markers.push(new maplibregl.Marker({element: el}).setLngLat([station.lon, station.lat]).addTo(map))
  }
}

function updateMarkers() {
  markers.forEach(m => m.remove())
  markers.length = 0
  for (const station of store.stations) {
    if (station.lon === null || station.lat === null) continue
    const el = document.createElement('div')
    el.innerHTML = getStationLabel(station)
    markers.push(new maplibregl.Marker({element: el}).setLngLat([station.lon, station.lat]).addTo(map))
  }
}

// ─── Camera helpers ───────────────────────────────────────────────────────────

function flyToCountry(animated = true) {
  if (props.countryBounds) {
    try {
      const [minLon, minLat, maxLon, maxLat] = JSON.parse(props.countryBounds)
      map.fitBounds([[minLon, minLat], [maxLon, maxLat]], {
        padding: 20,
        duration: animated ? FLY_DURATION_MS : 0,
        essential: true,
      })
      return
    } catch (_) { /* fall through */ }
  }
  // Fallback: fit to station coords
  const coords = store.stations.filter(s => s.lon !== null && s.lat !== null)
  if (!coords.length) return
  const bounds = coords.reduce((b, s) => b.extend([s.lon, s.lat]), new maplibregl.LngLatBounds())
  map.fitBounds(bounds, {padding: 80, maxZoom: 10, duration: animated ? FLY_DURATION_MS : 0})
}

function flyToStation(station) {
  map.flyTo({
    center: [station.lon, station.lat],
    zoom: STATION_ZOOM,
    duration: FLY_DURATION_MS,
    curve: 1.4,
    essential: true,
  })
}

// ─── Tour ─────────────────────────────────────────────────────────────────────

function advanceTour() {
  const stations = sortedStations.value
  if (!stations.length) return

  if (tourStep.value === -1) {
    // Was on country view → go to first station
    tourStep.value = 0
    flyToStation(stations[0])
  } else if (tourStep.value >= stations.length - 1) {
    // Finished all stations → return to country
    tourStep.value = -1
    flyToCountry(true)
  } else {
    // Next station
    tourStep.value++
    flyToStation(stations[tourStep.value])
  }
}

function startTour() {
  // Initial country fit (no animation — map just loaded)
  flyToCountry(false)
  // After TOUR_DWELL_MS begin the cycle
  tourTimer = setInterval(advanceTour, TOUR_DWELL_MS)
}

// ─── Parameter rotation ───────────────────────────────────────────────────────

function startParamRotation() {
  if (store.parameters.length <= 1) return
  paramTimer = setInterval(() => {
    currentParamIndex.value = (currentParamIndex.value + 1) % store.parameters.length
  }, props.rotationInterval * 1000)
}

// ─── Watchers ─────────────────────────────────────────────────────────────────

watch(currentParamIndex, () => { if (map) updateMarkers() })

watch(() => store.latestData, () => { if (map) updateMarkers() }, {deep: true})

// ─── Lifecycle ────────────────────────────────────────────────────────────────

onMounted(() => {
  map = new maplibregl.Map({
    container: mapContainer.value,
    style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
    center: [0, 0],
    zoom: 2,
    attributionControl: false,
  })
  map.on('load', async () => {
    await addCountryBoundary(map, props.countryIso3)
    buildMarkers()
    startTour()
    startParamRotation()
  })
})

onUnmounted(() => {
  if (tourTimer) clearInterval(tourTimer)
  if (paramTimer) clearInterval(paramTimer)
  if (map) map.remove()
})
</script>

<template>
  <div ref="mapContainer" class="overlay-map"></div>
</template>

<style>
.overlay-map {
  width: 100%;
  height: 100%;
}

.ol-marker {
  cursor: default;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.2rem;
}

.ol-station-name {
  background: rgba(15, 23, 42, 0.9);
  border: 1px solid rgba(56, 189, 248, 0.45);
  border-radius: 6px;
  padding: 0.25rem 0.6rem;
  color: #38bdf8;
  font-family: system-ui, -apple-system, sans-serif;
  font-size: clamp(0.75rem, 1.2vw, 1rem);
  font-weight: 700;
  white-space: nowrap;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.5);
}

.ol-param-row {
  display: flex;
  align-items: baseline;
  gap: 0.3rem;
  background: rgba(15, 23, 42, 0.88);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 0.35rem 0.7rem;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
}

.ol-param-icon {
  font-size: clamp(1.2rem, 2.2vw, 1.8rem);
  line-height: 1;
}

.ol-param-icon .fa-solid {
  font-size: inherit;
}

.ol-param-value {
  font-size: clamp(1.4rem, 2.8vw, 2.4rem);
  font-weight: 700;
  color: #f1f5f9;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

.ol-param-unit {
  font-size: clamp(0.7rem, 1.1vw, 0.9rem);
  color: #64748b;
  line-height: 1;
}

.ol-param-time {
  font-size: clamp(0.75rem, 1.2vw, 1rem);
  color: #94a3b8;
  font-variant-numeric: tabular-nums;
  text-align: center;
  background: rgba(15, 23, 42, 0.85);
  border-radius: 4px;
  padding: 0.1rem 0.4rem;
}
</style>
