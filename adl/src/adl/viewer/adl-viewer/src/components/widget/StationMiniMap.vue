<script setup>
import {onMounted, onUnmounted, ref, watch} from "vue"
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import {addCountryBoundary} from '@/composables/useCountryBoundary.js'

const props = defineProps({
    stations: {type: Array, default: () => []},
    activeId: {type: [Number, String], default: null},
    countryIso3: {type: String, default: ''},
})

const mapContainer = ref(null)
let map = null
const markerMap = {}

const BASEMAP_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'

function createMarker(station, isActive) {
    if (isActive) {
        return new maplibregl.Marker({color: '#38bdf8'})
            .setLngLat([station.lon, station.lat])
            .addTo(map)
    }
    const el = document.createElement('div')
    el.className = 'station-dot-inactive'
    return new maplibregl.Marker({element: el, anchor: 'center'})
        .setLngLat([station.lon, station.lat])
        .addTo(map)
}

function clearMarkers() {
    Object.values(markerMap).forEach(m => m.remove())
    Object.keys(markerMap).forEach(k => delete markerMap[k])
}

function buildMarkers(activeId) {
    props.stations
        .filter(s => s.lon !== null && s.lat !== null)
        .forEach(s => {
            markerMap[s.id] = createMarker(s, s.id === activeId)
        })
}

function fitAll() {
    const valid = props.stations.filter(s => s.lon !== null && s.lat !== null)
    if (!valid.length) return
    if (valid.length === 1) {
        map.setCenter([valid[0].lon, valid[0].lat])
        map.setZoom(6)
        return
    }
    const bounds = valid.reduce(
        (b, s) => b.extend([s.lon, s.lat]),
        new maplibregl.LngLatBounds()
    )
    map.fitBounds(bounds, {padding: 50, maxZoom: 8, animate: false})
}

function flyToActive(activeId) {
    const active = props.stations.find(s => s.id === activeId)
    if (active?.lon != null && active?.lat != null) {
        map.flyTo({center: [active.lon, active.lat], zoom: 6, duration: 1200, essential: true})
    }
}

watch(() => props.activeId, (activeId) => {
    if (!map) return
    clearMarkers()
    buildMarkers(activeId)
    flyToActive(activeId)
})

onMounted(() => {
    if (!mapContainer.value) return
    map = new maplibregl.Map({
        container: mapContainer.value,
        style: BASEMAP_STYLE,
        center: [0, 0],
        zoom: 2,
        interactive: false,
        attributionControl: false,
    })
    map.on('load', async () => {
        await addCountryBoundary(map, props.countryIso3)
        buildMarkers(props.activeId)
        fitAll()
    })
})

onUnmounted(() => { if (map) map.remove() })
</script>

<template>
    <div class="mini-map-wrap">
        <div ref="mapContainer" class="mini-map"></div>
    </div>
</template>

<style scoped>
.mini-map-wrap {
    width: 100%;
    height: 100%;
}

.mini-map {
    width: 100%;
    height: 100%;
    border-radius: 8px;
    overflow: hidden;
}
</style>

<style>
.station-dot-inactive {
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: rgba(148, 163, 184, 0.45);
    border: 2px solid rgba(148, 163, 184, 0.85);
    box-shadow: 0 0 8px rgba(148, 163, 184, 0.55), 0 0 20px rgba(148, 163, 184, 0.25);
}
</style>
