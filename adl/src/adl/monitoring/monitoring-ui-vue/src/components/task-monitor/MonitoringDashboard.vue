<template>
  <div class="task-monitoring-page">
    <ActiveTasksDashboard/>
  </div>
</template>

<script setup>
import ActiveTasksDashboard from './ActiveTasksDashboard.vue'
</script>

<style scoped>
.task-monitoring-page {
  min-height: 100vh;
  background: var(--surface-ground);
}
</style>