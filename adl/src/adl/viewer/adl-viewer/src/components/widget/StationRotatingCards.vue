<script setup>
import {computed, onUnmounted, watch} from "vue"
import {useWidgetStore} from "@/stores/widget.js"
import StationMiniMap from "@/components/widget/StationMiniMap.vue"
import {renderParamIcon} from "@/utils/paramIcons.js"

const props = defineProps({
  rotationInterval: {type: Number, default: 10},
  countryIso3: {type: String, default: ''},
})

const store = useWidgetStore()
let rotationTimer = null
const station = computed(() => store.currentStation)
const stationData = computed(() => store.currentStationData)
const currentIndex = computed(() => store.currentIndex)
const stationCount = computed(() => store.stationCount)

const parameterMap = computed(() => {
  const map = {}
  for (const p of store.parameters) map[p.id] = p
  return map
})

const displayRows = computed(() => {
  return stationData.value
      .filter(rec => parameterMap.value[rec.parameter_id])
      .map(rec => {
        const p = parameterMap.value[rec.parameter_id]
        return {
          name: p.name,
          iconHtml: renderParamIcon(p),
          value: rec.value !== null ? Number(rec.value).toFixed(1) : '—',
          unit: p.unit,
          time: rec.time,
        }
      })
})

const lastUpdated = computed(() => {
  if (!stationData.value.length) return null
  const times = stationData.value.map(r => new Date(r.time)).filter(Boolean)
  if (!times.length) return null
  const latest = new Date(Math.max(...times))
  return latest.toLocaleString(undefined, {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
    hour12: false,
  })
})

let rotationStarted = false

watch(() => store.stationCount, (count) => {
  if (count > 1 && !rotationStarted) {
    rotationStarted = true
    rotationTimer = setInterval(() => store.nextStation(), props.rotationInterval * 1000)
  }
}, {immediate: true})

onUnmounted(() => { if (rotationTimer) clearInterval(rotationTimer) })
</script>

<template>
  <div class="cards-root" v-if="station">
    <div class="layout">
      <div class="map-panel">
        <StationMiniMap
            :stations="store.stations"
            :active-id="station.id"
            :country-iso3="countryIso3"
        />
      </div>

      <div class="data-panel">
        <div class="station-name">{{ station.name }}</div>
        <div class="data-time" v-if="lastUpdated">{{ lastUpdated }}</div>
        <div class="divider"></div>

        <div class="params-grid" v-if="displayRows.length">
          <div class="param-card" v-for="row in displayRows" :key="row.name">
            <span class="param-icon" v-html="row.iconHtml"></span>
            <span class="param-label">{{ row.name.replace(/_/g, ' ') }}</span>
            <div class="param-reading">
              <span class="param-value">{{ row.value }}</span>
              <span class="param-unit">{{ row.unit }}</span>
            </div>
          </div>
        </div>
        <div class="no-data" v-else>No data available</div>

      </div>
    </div>

    <div class="footer">
      <span class="counter">{{ currentIndex + 1 }} of {{ stationCount }}</span>
      <div class="dots">
        <span
            v-for="(s, i) in store.stations"
            :key="s.id"
            class="dot"
            :class="{ active: i === currentIndex }"
            @click="store.goToStation(i)"
        ></span>
      </div>
      <div class="nav-btns">
        <button @click="store.prevStation()" class="nav-btn">&#8592;</button>
        <button @click="store.nextStation()" class="nav-btn">&#8594;</button>
      </div>
    </div>
  </div>

  <div class="empty" v-else>
    No stations configured.
  </div>
</template>

<style scoped>
.cards-root {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 1.5rem;
  gap: 1rem;
}

.layout {
  flex: 1;
  display: grid;
  grid-template-columns: 30% 1fr;
  gap: 1.5rem;
  min-height: 0;
}

.map-panel {
  height: 100%;
  border-radius: 10px;
  overflow: hidden;
}

.data-panel {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  overflow: hidden;
}

.station-name {
  font-size: clamp(1.8rem, 4vw, 3.5rem);
  font-weight: 700;
  color: #f1f5f9;
  line-height: 1.1;
  letter-spacing: -0.02em;
}

.data-time {
  font-size: clamp(1.3rem, 2.2vw, 1.8rem);
  color: #cbd5e1;
  font-variant-numeric: tabular-nums;
}

.divider {
  height: 2px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 1px;
}

.params-grid {
  flex: 1;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1.5rem;
  align-content: center;
  overflow: hidden;
}

.param-card {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  padding: 1.25rem 1rem;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.4rem;
}

.param-icon {
  font-size: clamp(1.6rem, 3vw, 2.8rem);
  line-height: 1;
}

.param-icon .fa-solid {
  font-size: inherit;
  color: #38bdf8;
}

.param-label {
  font-size: clamp(0.7rem, 1.1vw, 0.9rem);
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.param-reading {
  display: flex;
  align-items: baseline;
  gap: 0.3rem;
}

.param-value {
  font-size: clamp(1.6rem, 3.5vw, 3.2rem);
  font-weight: 700;
  color: #38bdf8;
  font-variant-numeric: tabular-nums;
}

.param-unit {
  font-size: clamp(0.8rem, 1.3vw, 1.1rem);
  color: #64748b;
}

.no-data {
  color: #475569;
  font-size: 1.2rem;
  flex: 1;
  display: flex;
  align-items: center;
}


.footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding-top: 0.5rem;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.counter {
  font-size: 0.9rem;
  color: #475569;
  min-width: 4rem;
}

.dots {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  justify-content: center;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.15);
  cursor: pointer;
  transition: background 0.2s;
}

.dot.active {
  background: #38bdf8;
}

.nav-btns {
  display: flex;
  gap: 0.5rem;
}

.nav-btn {
  background: rgba(255, 255, 255, 0.08);
  color: #94a3b8;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  width: 2.2rem;
  height: 2.2rem;
  font-size: 1rem;
  cursor: pointer;
  transition: background 0.2s;
}

.nav-btn:hover {
  background: rgba(255, 255, 255, 0.16);
}

.empty {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #475569;
  font-size: 1.2rem;
}
</style>
