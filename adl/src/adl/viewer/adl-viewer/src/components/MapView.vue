<script setup>
import {computed, onMounted, onUnmounted, ref, watch} from "vue";
import {useNetworkStore} from "@/stores/network.js";
import {useMapStore} from "@/stores/map.js";
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import NetworkConnectionSelect from "@/components/table-view/NetworkConnectionSelect.vue";
import DataParameterSelect from "@/components/map-view/DataParameterSelect.vue";
import ColorScaleLegend from "@/components/map-view/ColorScaleLegend.vue";
import Panel from 'primevue/panel';

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
  bounds: {
    type: String,
    required: false,
    default: null
  },
  latestRecordsMvtUrl: {
    type: String,
    required: true,
  }
});

const networkStore = useNetworkStore();
const mapStore = useMapStore();
const mapContainer = ref(null);
const map = ref(null);
const SOURCE_ID = 'observations-source';
const LAYER_ID = 'observations-layer';
const LABEL_LAYER_ID = 'observations-labels';

// Parse bounds string to array
const boundsArray = computed(() => {
  if (!props.bounds) return null;
  try {
    return JSON.parse(props.bounds);
  } catch (e) {
    console.error('Invalid bounds format:', e);
    return null;
  }
});

// Compute the tile URL based on selected values
const tileUrl = computed(() => {
  const connectionId = networkStore.selectedNetworkConnection;
  const parameterId = mapStore.selectedDataParameterId;

  if (!connectionId || !parameterId) return null;

  return `${props.latestRecordsMvtUrl}?connection_id=${connectionId}&parameter_id=${parameterId}`;
});

const selectedDataParameter = computed(() => {
  const connectionId = networkStore.selectedNetworkConnection;
  const parameterId = mapStore.selectedDataParameterId;

  if (!connectionId || !parameterId) return null;

  return networkStore.getSelectedNetworkConnectionDataParameter(connectionId, parameterId);
});

// Get the color scale or default color
const circleColor = computed(() => {
  const dataParam = selectedDataParameter.value;

  if (!dataParam) return '#007cbf';

  // If color_scale exists, use it
  if (dataParam.style?.color_scale) {
    return dataParam.style.color_scale;
  }

  // Default color if no style defined
  return '#007cbf';
});

// Check if legend should be shown - now shows whenever a parameter is selected
const showLegend = computed(() => {
  return selectedDataParameter.value !== null;
});

// Get color stops for legend (empty array if no color scale)
const colorStops = computed(() => {
  return selectedDataParameter.value?.style?.color_stops || [];
});

// Get parameter unit for legend
const parameterUnit = computed(() => {
  return selectedDataParameter.value?.unit?.symbol || '';
});

// Get parameter name for legend
const parameterName = computed(() => {
  return selectedDataParameter.value?.name || '';
});


// Format UTC time
const formatUtcTime = (utcTime) => {
  if (!utcTime) return null;

  try {
    const date = new Date(utcTime);
    return date.toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'UTC',
      timeZoneName: 'short'
    });
  } catch (error) {
    return utcTime; // Fallback to raw value if parsing fails
  }
};

// Generate popup HTML
const generatePopupHTML = (feature) => {
  const value = feature.properties.value;
  const utcTime = feature.properties.utc_time;
  const parameterName = selectedDataParameter.value?.name || 'Value';
  const unit = selectedDataParameter.value?.unit?.symbol || '';
  const formattedTime = formatUtcTime(utcTime);

  return `
    <div class="popup-container">
      <div class="popup-header">
        ${parameterName}
      </div>
      <div class="popup-value">
        ${value !== null && value !== undefined
      ? `${value} <span class="popup-unit">${unit}</span>`
      : '<span class="popup-no-data">No data</span>'}
      </div>
      ${formattedTime ? `
        <div class="popup-time">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <polyline points="12 6 12 12 16 14"></polyline>
          </svg>
          ${formattedTime}
        </div>
      ` : ''}
    </div>
  `;
};


// Create and show popup
const showPopup = (mapInstance, lngLat, feature) => {
  new maplibregl.Popup({
    closeButton: true,
    closeOnClick: true,
    maxWidth: '300px'
  })
      .setLngLat(lngLat)
      .setHTML(generatePopupHTML(feature))
      .addTo(mapInstance);
};


// Function to add or update the vector tile source and layer
const updateMapSource = () => {
  if (!map.value || !tileUrl.value) return;

  const mapInstance = map.value;

  // Remove existing layers and source if they exist
  if (mapInstance.getLayer(LABEL_LAYER_ID)) {
    mapInstance.removeLayer(LABEL_LAYER_ID);
  }
  if (mapInstance.getLayer(LAYER_ID)) {
    mapInstance.removeLayer(LAYER_ID);
  }
  if (mapInstance.getSource(SOURCE_ID)) {
    mapInstance.removeSource(SOURCE_ID);
  }

  // Add new source
  mapInstance.addSource(SOURCE_ID, {
    type: 'vector',
    tiles: [tileUrl.value],
    minzoom: 0,
    maxzoom: 22
  });

  // Add circle layer with data-driven styling
  mapInstance.addLayer({
    id: LAYER_ID,
    type: 'circle',
    source: SOURCE_ID,
    'source-layer': 'default', // Update this to match your tile layer name
    paint: {
      'circle-radius': 16,
      'circle-color': circleColor.value,
      'circle-stroke-width': 1,
      'circle-stroke-color': '#000'
    }
  });

  // Add label layer to show values in the middle of circles
  mapInstance.addLayer({
    id: LABEL_LAYER_ID,
    type: 'symbol',
    source: SOURCE_ID,
    'source-layer': 'default', // Update this to match your tile layer name
    layout: {
      'text-field': [
        'concat',
        ['to-string', ['round', ['get', 'value']]],
        ''
      ],
      'text-font': ['FiraSans-Bold'],
      'text-size': 11,
      'text-anchor': 'center',
      'text-allow-overlap': true,
      'text-ignore-placement': false
    },
    paint: {
      'text-color': '#ffffff',
      'text-halo-color': '#000000',
      'text-halo-width': 1
    }
  });
// Add click popup to show detailed information
  // Add click popup to show detailed information
  mapInstance.on('click', LAYER_ID, (e) => {
    if (e.features.length > 0) {
      showPopup(mapInstance, e.lngLat, e.features[0]);
    }
  });

  // Change cursor on hover
  mapInstance.on('mouseenter', LAYER_ID, () => {
    mapInstance.getCanvas().style.cursor = 'pointer';
  });

  mapInstance.on('mouseleave', LAYER_ID, () => {
    mapInstance.getCanvas().style.cursor = '';
  });
};

onMounted(() => {
  networkStore.loadNetworkConnections();

  // Initialize the map
  map.value = new maplibregl.Map({
    container: mapContainer.value,
    style: "https://geoserveis.icgc.cat/contextmaps/icgc_mapa_base_gris_simplificat.json",
    center: [0, 0],
    zoom: 2,
    attributionControl: {
      compact: true
    }
  });

  // add navigation control. Zoom in,out
  const navControl = new maplibregl.NavigationControl({
    showCompass: false
  })

  map.value.addControl(navControl, 'bottom-right')

  // Fit map to bounds if available
  if (boundsArray.value && boundsArray.value.length === 4) {
    const [lng1, lat1, lng2, lat2] = boundsArray.value;
    map.value.fitBounds([[lng1, lat1], [lng2, lat2]], {
      padding: 50
    });
  }

  // Wait for map to load before adding sources
  map.value.on('load', () => {
    if (tileUrl.value) {
      updateMapSource();
    }
  });
});

onUnmounted(() => {
  // Clean up the map instance
  map.value?.remove();
});

// Watch for changes in network connection
watch(() => networkStore.selectedNetworkConnection, (newValue) => {
  if (newValue) {
    mapStore.clearDataParameterState()
  }
}, {immediate: true})

// Watch for changes in tile URL and update the map
watch(tileUrl, (newUrl) => {
  if (newUrl && map.value?.loaded()) {
    updateMapSource();
  }
});

</script>

<template>
  <div ref="mapContainer" class="map-container">
    <Panel class="mv-selector-panel" toggleable>
      <div class="mv-selectors">
        <NetworkConnectionSelect
            :fetchDataParametersOnChange="true"
            :fetchStationsLinkOnChange="false"
        />
        <DataParameterSelect/>
      </div>
    </Panel>

    <!-- Color Scale Legend -->
    <div v-if="showLegend" class="legend-container">
      <ColorScaleLegend
          :color-stops="colorStops"
          :unit="parameterUnit"
          :parameter-name="parameterName"
          :width="400"
          :height="20"
      />
    </div>
  </div>
</template>

<style scoped>
.map-container {
  position: relative;
  width: 100%;
  height: 100%;
}

.mv-selector-panel {
  position: absolute;
  top: 1rem;
  left: 1rem;
  z-index: 2;
}

.mv-selectors {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.legend-container {
  position: absolute;
  bottom: 2.5rem;
  left: 50%;
  transform: translateX(-50%);
  z-index: 2;
}

/* Popup styling */
.map-container :deep(.maplibregl-popup-content) {
  padding: 0;
  border-radius: 8px;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
}

.map-container :deep(.maplibregl-popup-close-button) {
  font-size: 20px;
  color: #6b7280;
  padding: 4px 8px;
  right: 4px;
  top: 4px;
}

.map-container :deep(.maplibregl-popup-close-button):hover {
  background-color: #f3f4f6;
  color: #111827;
  border-radius: 4px;
}

.map-container :deep(.maplibregl-popup-tip) {
  border-top-color: white;
}

/* Popup content classes */
.map-container :deep(.popup-container) {
  padding: 12px;
  font-family: 'Roboto', Arial, sans-serif;
  min-width: 180px;
}

.map-container :deep(.popup-header) {
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 2px solid #e5e7eb;
}

.map-container :deep(.popup-value) {
  font-size: 24px;
  font-weight: 700;
  color: #111827;
  margin-bottom: 4px;
}

.map-container :deep(.popup-unit) {
  font-size: 16px;
  font-weight: 500;
  color: #6b7280;
}

.map-container :deep(.popup-no-data) {
  color: #9ca3af;
}

.map-container :deep(.popup-time) {
  font-size: 12px;
  color: #6b7280;
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.map-container :deep(.popup-time svg) {
  flex-shrink: 0;
}
</style>