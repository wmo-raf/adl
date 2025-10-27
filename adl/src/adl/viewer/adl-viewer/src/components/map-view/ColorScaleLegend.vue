<script setup>
import {computed} from 'vue';

const props = defineProps({
  colorStops: {
    type: Array,
    required: true,
    // Expected format: [{ value: 0, color: '#FF00FF', label: 'Cold' }, ...]
  },
  width: {
    type: Number,
    default: 400
  },
  height: {
    type: Number,
    default: 20
  },
  showLabels: {
    type: Boolean,
    default: true
  },
  unit: {
    type: String,
    default: ''
  },
  parameterName: {
    type: String,
    default: ''
  }
});

// Check if we have color stops
const hasColorStops = computed(() => {
  return props.colorStops && props.colorStops.length > 0;
});

// Generate SVG gradient stops
const gradientStops = computed(() => {
  if (!hasColorStops.value) return [];

  const sortedStops = [...props.colorStops].sort((a, b) => a.value - b.value);
  const minValue = sortedStops[0].value;
  const maxValue = sortedStops[sortedStops.length - 1].value;
  const range = maxValue - minValue;

  return sortedStops.map(stop => {
    const offset = range === 0 ? 0 : ((stop.value - minValue) / range) * 100;
    return {
      offset: `${offset}%`,
      color: stop.color
    };
  });
});

// Generate label positions
const labelPositions = computed(() => {
  if (!hasColorStops.value) return [];

  const sortedStops = [...props.colorStops].sort((a, b) => a.value - b.value);
  const minValue = sortedStops[0].value;
  const maxValue = sortedStops[sortedStops.length - 1].value;
  const range = maxValue - minValue;

  // For better distribution, we can either show all stops or select key ones
  // Here we'll show up to 5 evenly distributed labels
  const maxLabels = 5;
  let labelsToShow = sortedStops;

  if (sortedStops.length > maxLabels) {
    const step = Math.floor(sortedStops.length / (maxLabels - 1));
    labelsToShow = sortedStops.filter((_, index) =>
        index % step === 0 || index === sortedStops.length - 1
    );
    // Ensure we don't have duplicates
    labelsToShow = [...new Map(labelsToShow.map(item => [item.value, item])).values()];
  }

  return labelsToShow.map(stop => {
    const offset = range === 0 ? 0 : ((stop.value - minValue) / range);
    const x = offset * (props.width - 40) + 20; // 20px padding on each side
    return {
      x,
      value: Math.round(stop.value * 10) / 10, // Round to 1 decimal
      label: stop.label
    };
  });
});

const gradientId = computed(() => `gradient-${Math.random().toString(36).substr(2, 9)}`);
</script>

<template>
  <div class="color-scale-legend">
    <div class="legend-title">
      {{ parameterName }}
      <span v-if="unit" class="unit-badge">({{ unit }})</span>
    </div>

    <!-- Show color gradient only if color stops are available -->
    <svg v-if="hasColorStops" :width="width" :height="height + (showLabels ? 15 : 0)">
      <defs>
        <linearGradient :id="gradientId" x1="0%" x2="100%" y1="0%" y2="0%">
          <stop
              v-for="(stop, index) in gradientStops"
              :key="index"
              :offset="stop.offset"
              :stop-color="stop.color"
          />
        </linearGradient>
      </defs>

      <!-- Color bar -->
      <rect
          x="20"
          y="0"
          :width="width - 40"
          :height="height"
          :style="{ fill: `url(#${gradientId})` }"
          rx="2"
      />

      <!-- Labels -->
      <g v-if="showLabels">
        <text
            v-for="(label, index) in labelPositions"
            :key="index"
            :x="label.x"
            :y="height + 12"
            text-anchor="middle"
            class="legend-label"
        >
          {{ label.value }}
        </text>
      </g>
    </svg>
  </div>
</template>

<style scoped>
.color-scale-legend {
  display: inline-block;
  background: rgba(255, 255, 255, 0.95);
  padding: 10px 12px;
  border-radius: 4px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

.legend-title {
  font-family: 'Roboto', Arial, sans-serif;
  font-size: 12px;
  font-weight: 600;
  color: #333;
  text-align: center;
  margin-bottom: 6px;
}

.unit-badge {
  font-weight: 400;
  color: #666;
  margin-left: 4px;
}

.legend-label {
  font-family: 'Roboto', Arial, sans-serif;
  font-size: 11px;
  fill: #333;
  font-weight: 500;
  text-shadow: 0 0 2px rgba(255, 255, 255, 0.9),
  1px 0 2px rgba(255, 255, 255, 0.9),
  -1px 0 2px rgba(255, 255, 255, 0.9),
  0 1px 2px rgba(255, 255, 255, 0.9),
  0 -1px 2px rgba(255, 255, 255, 0.9);
}
</style>