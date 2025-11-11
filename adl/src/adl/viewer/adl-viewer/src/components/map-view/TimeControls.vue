<script setup>
import {computed, onBeforeUnmount, onMounted, ref} from 'vue';
import DatePicker from 'primevue/datepicker';


const props = defineProps({
  initialDate: {
    type: Date,
    default: () => {
      const now = new Date();
      now.setSeconds(0);
      now.setMilliseconds(0);
      return now;
    }
  }
});

const emit = defineEmits(['timeChange']);
// Reactive state
const currentTime = ref(new Date(props.initialDate));
const maxTime = ref(new Date()); // Current time as maximum
const offset = ref(0);
const isDragging = ref(false);
const dragStartX = ref(0);
const timelineWrapper = ref(null);
const dragStartTime = ref(null); // Store the time when drag started

// Constants
const PIXELS_PER_MINUTE = 2;
const MINUTES_INTERVAL = 5;


const visibleMarks = computed(() => {
  const marks = [];
  const centerTime = currentTime.value.getTime();
  const currentMaxTime = maxTime.value.getTime();
  const wrapperWidth = timelineWrapper.value?.offsetWidth || 800;

  // Calculate how many marks we need to show (with buffer)
  const visibleMinutes = (wrapperWidth / PIXELS_PER_MINUTE) + 120; // Extra buffer
  const startTime = centerTime - (visibleMinutes / 2) * 60 * 1000;
  const endTime = centerTime + (visibleMinutes / 2) * 60 * 1000;

  // Round to nearest 5-minute interval
  const startDate = new Date(startTime);
  startDate.setMinutes(Math.floor(startDate.getMinutes() / MINUTES_INTERVAL) * MINUTES_INTERVAL);
  startDate.setSeconds(0);
  startDate.setMilliseconds(0);

  let currentMark = new Date(startDate);

  while (currentMark.getTime() <= endTime) {
    const diffMinutes = (currentMark.getTime() - centerTime) / (60 * 1000);
    const position = (wrapperWidth / 2) + (diffMinutes * PIXELS_PER_MINUTE) + offset.value;

    const isHour = currentMark.getMinutes() === 0;
    const isFuture = currentMark.getTime() > currentMaxTime;

    marks.push({
      timestamp: currentMark.getTime(),
      position,
      isHour,
      isFuture,
      label: String(currentMark.getHours()).padStart(2, '0')
    });

    currentMark = new Date(currentMark.getTime() + MINUTES_INTERVAL * 60 * 1000);
  }

  return marks;
});

function startDrag(e) {
  isDragging.value = true;
  dragStartX.value = e.type.includes('mouse') ? e.clientX : e.touches[0].clientX;
  dragStartTime.value = new Date(currentTime.value); // Store the starting time

  if (timelineWrapper.value) {
    timelineWrapper.value.style.cursor = 'grabbing';
  }
}

function onDrag(e) {
  if (!isDragging.value) return;

  const currentX = e.type.includes('mouse') ? e.clientX : e.touches[0].clientX;
  const deltaX = currentX - dragStartX.value;

  // Calculate the target time based on drag distance
  const minutesMoved = -deltaX / PIXELS_PER_MINUTE;
  let targetTime = new Date(currentTime.value.getTime() + minutesMoved * 60 * 1000);

  // Snap to fixed 5-minute intervals (00, 05, 10, 15, 20, etc.)
  const snappedMinutes = Math.round(targetTime.getMinutes() / MINUTES_INTERVAL) * MINUTES_INTERVAL;
  targetTime.setMinutes(snappedMinutes);
  targetTime.setSeconds(0);
  targetTime.setMilliseconds(0);

  // Check if we've actually moved to a different snapped time
  if (targetTime.getTime() === currentTime.value.getTime()) {
    return;
  }

  // Prevent going into the future
  if (targetTime.getTime() > maxTime.value.getTime()) {
    targetTime = new Date(maxTime.value);
  }

  // Update the current time and reset drag for next step
  currentTime.value = targetTime;
  dragStartX.value = currentX;
  offset.value = 0;

  // DO NOT emit timeChange here during dragging
}

function endDrag() {
  if (isDragging.value) {
    isDragging.value = false;
    offset.value = 0;

    if (timelineWrapper.value) {
      timelineWrapper.value.style.cursor = 'grab';
    }

    // Only emit timeChange when dragging stops AND if the time actually changed
    if (dragStartTime.value && dragStartTime.value.getTime() !== currentTime.value.getTime()) {
      emit('timeChange', currentTime.value);
    }

    dragStartTime.value = null; // Reset the drag start time
  }
}

function jumpBackward(interval) {
  let milliseconds = 0;

  switch (interval) {
    case '5min':
      milliseconds = 5 * 60 * 1000;
      break;
    case 'hour':
      milliseconds = 60 * 60 * 1000;
      break;
    case 'day':
      milliseconds = 24 * 60 * 60 * 1000;
      break;
  }

  currentTime.value = new Date(currentTime.value.getTime() - milliseconds);
  emit('timeChange', currentTime.value);
}

function jumpForward(interval) {
  let milliseconds = 0;

  switch (interval) {
    case '5min':
      milliseconds = 5 * 60 * 1000;
      break;
    case 'hour':
      milliseconds = 60 * 60 * 1000;
      break;
    case 'day':
      milliseconds = 24 * 60 * 60 * 1000;
      break;
  }

  let newTime = new Date(currentTime.value.getTime() + milliseconds);

  // Prevent going into the future
  if (newTime.getTime() > maxTime.value.getTime()) {
    newTime = new Date(maxTime.value);
  }

  currentTime.value = newTime;
  emit('timeChange', currentTime.value);
}

function refresh() {
  // Update maxTime to the current time NOW without rounding
  const now = new Date();
  now.setSeconds(0);
  now.setMilliseconds(0);

  maxTime.value = new Date(now);
  currentTime.value = new Date(now);
  offset.value = 0;
  emit('timeChange', currentTime.value);
}

// Lifecycle
onMounted(() => {
  document.addEventListener('mousemove', onDrag);
  document.addEventListener('mouseup', endDrag);
  document.addEventListener('touchmove', onDrag);
  document.addEventListener('touchend', endDrag);
});

onBeforeUnmount(() => {
  document.removeEventListener('mousemove', onDrag);
  document.removeEventListener('mouseup', endDrag);
  document.removeEventListener('touchmove', onDrag);
  document.removeEventListener('touchend', endDrag);
});
</script>

<template>
  <div class="timeline-container">
    <!-- Date/Time Display -->
    <div class="datetime-display">
      <DatePicker
          v-model="currentTime"
          showTime
          hourFormat="24"
          touchUI
          :maxDate="maxTime"
          :manualInput="false"
          size="small"
          class="timeline-calendar-popup"
          @date-select="(value) => emit('timeChange', value)"
      />
    </div>

    <!-- Timeline Controls -->
    <div class="timeline-controls">
      <!-- Navigation Buttons -->
      <div class="nav-buttons">
        <button
            @click="jumpBackward('day')"
            class="nav-btn"
            title="Decrease by a day"
        >
          <svg viewBox="0 0 24 24" width="20" height="20">
            <path d="M18.41 16.59 13.82 12l4.59-4.59L17 6l-6 6 6 6zM6 6h2v12H6z" fill="currentColor"/>
          </svg>
        </button>

        <button
            @click="jumpBackward('5min')"
            class="nav-btn"
            title="Decrease by 5 minutes"
        >
          <svg viewBox="0 0 24 24" width="20" height="20">
            <path d="M15.41 7.41 14 6l-6 6 6 6 1.41-1.41L10.83 12z" fill="currentColor"/>
          </svg>
        </button>

        <button
            @click="jumpBackward('hour')"
            class="nav-btn"
            title="Decrease by an hour"
        >
          <svg viewBox="0 0 24 24" width="20" height="20" stroke="currentColor" fill="none" stroke-width="2">
            <polyline points="11 17 6 12 11 7"></polyline>
            <polyline points="18 17 13 12 18 7"></polyline>
          </svg>
        </button>
      </div>

      <!-- Timeline Slider -->
      <div
          ref="timelineWrapper"
          class="timeline-wrapper"
          @mousedown="startDrag"
          @touchstart="startDrag"
      >
        <div
            class="timeline-track"
            :style="{ transform: `translateX(${offset}px)` }"
        >
          <div
              v-for="mark in visibleMarks"
              :key="mark.timestamp"
              class="time-mark"
              :class="{ 'future-mark': mark.isFuture }"
              :style="{ left: `${mark.position}px` }"
          >
            <div v-if="mark.isHour" class="label">{{ mark.label }}</div>
            <div class="tick" :class="{ 'hour-tick': mark.isHour }"></div>
          </div>
        </div>

        <!-- Center Indicator Line -->
        <div class="center-line"></div>
      </div>

      <!-- Navigation Buttons (Right) -->
      <div class="nav-buttons">
        <button
            @click="jumpForward('5min')"
            class="nav-btn"
            title="Increase by 5 minutes"
        >
          <svg viewBox="0 0 24 24" width="20" height="20">
            <path d="M8.59 16.59 13.17 12 8.59 7.41 10 6l6 6-6 6z" fill="currentColor"/>
          </svg>
        </button>

        <button
            @click="jumpForward('hour')"
            class="nav-btn"
            title="Increase by an hour"
        >
          <svg viewBox="0 0 24 24" width="20" height="20" stroke="currentColor" fill="none" stroke-width="2">
            <polyline points="13 17 18 12 13 7"></polyline>
            <polyline points="6 17 11 12 6 7"></polyline>
          </svg>
        </button>

        <button
            @click="jumpForward('day')"
            class="nav-btn"
            title="Increase by a day"
        >
          <svg viewBox="0 0 24 24" width="20" height="20">
            <path d="M5.59 7.41 10.18 12l-4.59 4.59L7 18l6-6-6-6zM16 6h2v12h-2z" fill="currentColor"/>
          </svg>
        </button>

        <button
            @click="refresh"
            class="nav-btn refresh-btn"
            title="Refresh"
        >
          <svg viewBox="0 0 24 24" width="20" height="20">
            <path
                d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"
                fill="currentColor"/>
          </svg>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.timeline-container {
  width: 100%;
  position: relative;
}

.datetime-display {
  margin-bottom: 0.5rem;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.datetime-stack {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 16px;
  background: #fff;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.2s;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.datetime-stack:hover {
  background: #eeeeee;
}

.datetime-main {
  font-size: 14px;
  font-weight: 500;
  color: #333;
}

.datetime-sub {
  font-size: 12px;
  color: #757575;
}

.timeline-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.nav-buttons {
  display: flex;
  gap: 4px;
}

.nav-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  background: #fff;
  color: #616161;
  cursor: pointer;
  transition: all 0.2s;
}

.nav-btn:hover {
  background: #f5f5f5;
  border-color: #bdbdbd;
}

.nav-btn:active {
  background: #eeeeee;
}

.refresh-btn {
  color: #4caf50;
}

.timeline-wrapper {
  position: relative;
  flex: 1;
  min-width: 400px;
  max-width: 1200px;
  height: 32px;
  background: #f5f5f5;
  border-radius: 2px;
  overflow: hidden;
  cursor: grab;
  user-select: none;
}

.timeline-track {
  position: absolute;
  width: 100%;
  height: 100%;
  left: 0;
  top: 0;
  pointer-events: none;
}

.time-mark {
  position: absolute;
  bottom: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  pointer-events: none;
  transform: translateX(-50%);
}

.future-mark .tick {
  background: #d0d0d0 !important;
}

.future-mark .label {
  color: #bdbdbd !important;
}

.tick {
  width: 1px;
  height: 8px;
  background: #9e9e9e;
}

.hour-tick {
  width: 2px;
  height: 20px;
  background: #424242;
}

.label {
  font-size: 12px;
  color: #616161;
  margin-bottom: 2px;
  font-weight: 500;
}

.center-line {
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 2px;
  background: #f44336;
  transform: translateX(-50%);
  pointer-events: none;
  z-index: 100;
}
</style>