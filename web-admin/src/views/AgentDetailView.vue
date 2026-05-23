<template>
  <div class="agent-detail-view">
    <h1>Agent Detail</h1>
    <p>ID: {{ id }}</p>
  </div>
</template>

<script setup>
defineProps({ id: String });
</script>
