<script setup>
import {format} from 'date-fns'
import {computed, watch} from "vue";
import {useStationStore} from "@/stores/station.js";

const stationStore = useStationStore()

const formattedDateRange = computed(() => {
  const dates = stationStore.selectedStationLinkDetail?.data_dates
  if (!dates) return {from: '', to: ''}

  return {
    from: dates.earliest_time ? format(new Date(dates.earliest_time), 'dd MMM yyyy HH:mm') : "-",
    to: dates.latest_time ? format(new Date(dates.latest_time), 'dd MMM yyyy HH:mm') : "-"
  }
})

watch(() => stationStore.selectedStationId, (newStationId) => {
  if (newStationId) {
    stationStore.loadStationLinkDetail(newStationId)
  }
}, {immediate: true})

</script>

<template>
  <div v-if="stationStore.selectedStationLinkDetail" class="station-detail">
    <h2 class="station-name">
      {{ stationStore.selectedStationLinkDetail.station.name }}
    </h2>
    <div class="station-meta-item">
      <div class="meta-label"> WIGOS ID:</div>
      <div class="meta-value">
        {{ stationStore.selectedStationLinkDetail.station.wigos_id }}
      </div>
    </div>
    <div class="station-meta-item">
      <div class="meta-label"> Station Link ID:</div>
      <div class="meta-value">
        {{ stationStore.selectedStationLinkDetail.id }}
      </div>
    </div>
    <div class="station-meta-item">
      <div class="meta-label"> Connection ID:</div>
      <div class="meta-value">
        {{ stationStore.selectedStationLinkDetail.network_connection }}
      </div>
    </div>
    <div class="station-meta-item">
      <div class="meta-label"> Network:</div>
      <div class="meta-value">
        {{ stationStore.selectedStationLinkDetail.station.network.name }}
      </div>
    </div>
    <div class="station-meta-item">
      <div class="meta-label"> Location:</div>
      <div class="meta-value">
        lat: {{ stationStore.selectedStationLinkDetail.station.location.latitude }}, lon: {{
          stationStore.selectedStationLinkDetail.station.location.longitude
        }}
      </div>
    </div>
    <div class="station-meta-item" v-if="stationStore.selectedStationLinkDetail.data_dates">
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