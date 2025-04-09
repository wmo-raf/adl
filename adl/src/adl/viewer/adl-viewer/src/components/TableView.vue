<script setup>
import {onMounted} from "vue";
import Card from 'primevue/card';

import NetworkConnectionSelect from "@/components/table-view/NetworkConnectionSelect.vue";
import StationSelect from "@/components/table-view/StationSelect.vue";

import {useTableViewStore} from '@/stores/tableView'

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
});

const tableViewStore = useTableViewStore()

onMounted(() => {
  tableViewStore.loadDataParameters()
})

</script>

<template>
  <Card>
    <template #content>
      <div class="tv-header">
        <NetworkConnectionSelect/>
        <StationSelect/>
      </div>
    </template>
  </Card>

</template>

<style scoped>

.tv-header {
  display: flex;
  gap: 40px;
}

</style>