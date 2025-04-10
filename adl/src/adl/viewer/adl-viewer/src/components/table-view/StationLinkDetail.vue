<script setup>
import {format} from 'date-fns'
import {useTableViewStore} from '@/stores/tableView'
import {computed} from "vue";

const tableViewStore = useTableViewStore()

const formattedDateRange = computed(() => {
  const dates = tableViewStore.selectedStationLinkDetail?.data_dates
  if (!dates) return {from: '', to: ''}

  return {
    from: format(new Date(dates.earliest_time), 'dd MMM yyyy HH:mm'),
    to: format(new Date(dates.latest_time), 'dd MMM yyyy HH:mm')
  }
})

</script>

<template>
  <div v-if="tableViewStore.selectedStationLinkDetail" class="station-detail">
    <h2 class="station-name">
      {{ tableViewStore.selectedStationLinkDetail.station.name }}
    </h2>
    <div class="station-meta-item">
      <div class="meta-label"> WIGOS ID:</div>
      <div class="meta-value">
        {{ tableViewStore.selectedStationLinkDetail.station.wigos_id }}
      </div>
    </div>
    <div class="station-meta-item">
      <div class="meta-label"> Network:</div>
      <div class="meta-value">
        {{ tableViewStore.selectedStationLinkDetail.station.network.name }}
      </div>
    </div>
    <div class="station-meta-item">
      <div class="meta-label"> Location:</div>
      <div class="meta-value">
        lat: {{ tableViewStore.selectedStationLinkDetail.station.location.latitude }}, lon: {{
          tableViewStore.selectedStationLinkDetail.station.location.longitude
        }}
      </div>
    </div>
    <div class="station-meta-item" v-if="tableViewStore.selectedStationLinkDetail.data_dates">
      <div class="meta-label"> Archive:</div>
      <div class="meta-value">
        {{ formattedDateRange.from }} - {{ formattedDateRange.to }}
      </div>
    </div>

  </div>

</template>

<style scoped>

.station-detail {
  display: flex;
  flex-direction: column;
}

.station-name {
  font-size: 20px;
  font-weight: bold;
  margin-bottom: 10px;
}

.station-meta-item {
  display: flex;
  gap: 10px;
  margin-bottom: 10px;
}

.meta-label {
  font-weight: 600;
}

.meta-value {
  font-weight: 400;
}


</style>