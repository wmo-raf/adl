<script setup>
import {computed, onMounted, onUnmounted, ref, watch} from "vue";
import {useNetworkStore} from "@/stores/network.js";
import {useMapStore} from "@/stores/map.js";
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import NetworkConnectionSelect from "@/components/table-view/NetworkConnectionSelect.vue";
import DataParameterSelect from "@/components/map-view/DataParameterSelect.vue";
import MapVisualizationType from "@/components/map-view/MapVisualizationType.vue";
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
  tileservBaseUrl: {
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
const HEATMAP_LAYER_ID = 'observations-heatmap';

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

  return `${props.tileservBaseUrl}/public.obs_records_latest_mvt/{z}/{x}/{y}.pbf?in_connection_id=${connectionId}&in_parameter_id=${parameterId}`;
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

// Get heatmap color configuration
const heatmapColor = computed(() => {
  const dataParam = selectedDataParameter.value;

  if (!dataParam?.style?.color_stops || dataParam.style.color_stops.length === 0) {
    // Default heatmap colors
    return [
      'interpolate',
      ['linear'],
      ['heatmap-density'],
      0, 'rgba(33,102,172,0)',
      0.2, 'rgb(103,169,207)',
      0.4, 'rgb(209,229,240)',
      0.6, 'rgb(253,219,199)',
      0.8, 'rgb(239,138,98)',
      1, 'rgb(178,24,43)'
    ];
  }

  // Use color stops from style for heatmap
  const sortedStops = [...dataParam.style.color_stops].sort((a, b) => a.value - b.value);

  const heatmapExpression = [
    'interpolate',
    ['linear'],
    ['heatmap-density']
  ];

  // Add starting transparent color
  heatmapExpression.push(0);
  heatmapExpression.push('rgba(0,0,0,0)');

  // Map density (0-1) to colors, ensuring strict ascending order
  sortedStops.forEach((stop, index) => {
    // Calculate density as a value between 0 and 1
    const density = (index + 1) / sortedStops.length;
    const hex = stop.color;
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);

    heatmapExpression.push(density);
    heatmapExpression.push(`rgba(${r},${g},${b},1)`);
  });

  return heatmapExpression;
});

// Get the min and max values for heatmap weight calculation
const heatmapWeightRange = computed(() => {
  const dataParam = selectedDataParameter.value;

  if (!dataParam?.style?.color_stops || dataParam.style.color_stops.length === 0) {
    return {min: 0, max: 100}; // Default range
  }

  const sortedStops = [...dataParam.style.color_stops].sort((a, b) => a.value - b.value);
  return {
    min: sortedStops[0].value,
    max: sortedStops[sortedStops.length - 1].value
  };
});

// Function to add or update the vector tile source and layer
const updateMapSource = () => {
  if (!map.value || !tileUrl.value) return;

  const mapInstance = map.value;
  const visualizationType = mapStore.visualizationType || 'circle';

  // Remove all existing layers
  if (mapInstance.getLayer(LABEL_LAYER_ID)) {
    mapInstance.removeLayer(LABEL_LAYER_ID);
  }
  if (mapInstance.getLayer(HEATMAP_LAYER_ID)) {
    mapInstance.removeLayer(HEATMAP_LAYER_ID);
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

  if (visualizationType === 'heatmap') {
    const weightRange = heatmapWeightRange.value;

    // Add heatmap layer
    mapInstance.addLayer({
      id: HEATMAP_LAYER_ID,
      type: 'heatmap',
      source: SOURCE_ID,
      'source-layer': 'default',
      paint: {
        // Normalize the heatmap weight based on actual data range
        'heatmap-weight': [
          'interpolate',
          ['linear'],
          ['get', 'value'],
          weightRange.min, 0,
          weightRange.max, 1
        ],
        // Increase the heatmap color intensity based on zoom level
        'heatmap-intensity': [
          'interpolate',
          ['linear'],
          ['zoom'],
          0, 0.5,
          9, 1
        ],
        // Color ramp for heatmap
        'heatmap-color': heatmapColor.value,
        // Adjust the heatmap radius by zoom level
        'heatmap-radius': [
          'interpolate',
          ['linear'],
          ['zoom'],
          0, 10,
          5, 20,
          9, 40
        ],
        // Transition from heatmap to circle layer by zoom level
        'heatmap-opacity': [
          'interpolate',
          ['linear'],
          ['zoom'],
          7, 1,
          9, 0.5
        ]
      }
    });

    // Add a circle layer on top for point visualization at high zoom
    mapInstance.addLayer({
      id: LAYER_ID,
      type: 'circle',
      source: SOURCE_ID,
      'source-layer': 'default',
      minzoom: 10,
      paint: {
        'circle-radius': [
          'interpolate',
          ['linear'],
          ['zoom'],
          10, 5,
          15, 10
        ],
        'circle-color': circleColor.value,
        'circle-stroke-color': 'white',
        'circle-stroke-width': 1,
        'circle-opacity': [
          'interpolate',
          ['linear'],
          ['zoom'],
          10, 0,
          11, 1
        ]
      }
    });
  } else {
    // Add circle layer with data-driven styling
    mapInstance.addLayer({
      id: LAYER_ID,
      type: 'circle',
      source: SOURCE_ID,
      'source-layer': 'default',
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
      'source-layer': 'default',
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
  }

  // Add click popup to show detailed information (works for both visualizations)
  const clickLayerId = visualizationType === 'heatmap' ? HEATMAP_LAYER_ID : LAYER_ID;

  mapInstance.on('click', clickLayerId, (e) => {
    if (e.features.length > 0) {
      const feature = e.features[0];
      const value = feature.properties.value;
      const unit = selectedDataParameter.value?.unit?.symbol || '';

      new maplibregl.Popup()
          .setLngLat(e.lngLat)
          .setHTML(`
          <div style="padding: 8px;">
            <strong>${selectedDataParameter.value?.name || 'Value'}</strong><br>
            ${value !== null && value !== undefined ? `${value} ${unit}` : 'No data'}
          </div>
        `)
          .addTo(mapInstance);
    }
  });

  // Change cursor on hover
  mapInstance.on('mouseenter', clickLayerId, () => {
    mapInstance.getCanvas().style.cursor = 'pointer';
  });

  mapInstance.on('mouseleave', clickLayerId, () => {
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

// Watch for changes in visualization type
watch(() => mapStore.visualizationType, () => {
  if (map.value?.loaded() && tileUrl.value) {
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
        <MapVisualizationType/>
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
</style>