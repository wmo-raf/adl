<script setup>
import {computed} from 'vue';
import {useMapStore} from '@/stores/map.js';
import Select from 'primevue/select';

const mapStore = useMapStore();

const visualizationTypes = [
  {label: 'Points', value: 'circle'},
  {label: 'Heatmap', value: 'heatmap'}
];

const selectedVisualizationType = computed({
  get: () => mapStore.visualizationType || 'circle',
  set: (value) => mapStore.setVisualizationType(value)
});
</script>

<template>
  <div class="visualization-type-select">
    <label class="select-label">Visualization</label>
    <Select
        v-model="selectedVisualizationType"
        :options="visualizationTypes"
        optionLabel="label"
        optionValue="value"
        placeholder="Select visualization type"
        class="w-full"
    />
  </div>
</template>

<style scoped>
.visualization-type-select {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.select-label {
  font-size: 0.875rem;
  font-weight: 500;
  color: #374151;
}
</style>