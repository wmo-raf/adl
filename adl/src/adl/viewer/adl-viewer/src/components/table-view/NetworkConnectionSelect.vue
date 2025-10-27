<script setup>
import {onMounted, watch} from 'vue'
import Select from 'primevue/select';

import {useNetworkStore} from "@/stores/network.js";


const props = defineProps({
  fetchStationsLinkOnChange: {
    type: Boolean,
    default: true,
    required: false
  },
  fetchDataParametersOnChange: {
    type: Boolean,
    default: false,
    required: false
  }
})

const networkStore = useNetworkStore()

onMounted(() => {
  networkStore.loadNetworkConnections()
})

watch(() => networkStore.selectedNetworkConnection, (newValue) => {
  if (newValue && props.fetchStationsLinkOnChange) {
    networkStore.loadNetworkConnectionStations(newValue)
  }

  if (newValue && props.fetchDataParametersOnChange) {
    networkStore.loadNetworkConnectionDataParameters(newValue)
  }

}, {immediate: true})


</script>

<template>
  <div class="c-selector">
    <div class="c-selector-title">
      Select Network Connection
    </div>
    <Select
        v-model="networkStore.selectedNetworkConnection"
        :options="networkStore.networkConnections"
        optionLabel="name" optionValue="id" placeholder="Select a connection"></Select>
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