<script setup>
import {computed, watch} from 'vue'
import Select from 'primevue/select';

import {useMapStore} from "@/stores/map.js";
import {useNetworkStore} from "@/stores/network.js";

const mapStore = useMapStore()
const networkStore = useNetworkStore()

const selectedNetworkConnectionDataParameters = computed(() => {
  const selectedNetworkConnection = networkStore.selectedNetworkConnection
  return networkStore.getNetworkConnectionDataParameters(selectedNetworkConnection)
});

watch(() => mapStore.selectedDataParameterId, (newDataParameterId) => {
  if (newDataParameterId) {
  }
}, {immediate: true})

</script>

<template>
  <div class="c-selector">
    <div class="c-selector-title">
      Select Data Parameter
    </div>
    <Select v-model="mapStore.selectedDataParameterId"
            :options="selectedNetworkConnectionDataParameters"
            :disabled="!networkStore.selectedNetworkConnection"
            :loading="networkStore.loading"
            optionLabel="name"
            optionValue="id"
            placeholder="Select Data Parameter"
    />
  </div>
</template>

<style scoped>

.c-selector {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.c-selector-title {
  font-size: 14px;
  font-weight: bold;
}

</style>