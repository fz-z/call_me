<template>
  <div class="user-detail-view">
    <h1>User Detail</h1>
    <p>Username: {{ username }}</p>
  </div>
</template>

<script setup>
defineProps({ username: String });
</script>
