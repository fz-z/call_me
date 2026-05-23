<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal" style="min-width: 380px">
      <h3>授权 "{{ agent.alias }}"</h3>

      <!-- Searchable user dropdown -->
      <div class="dropdown-wrapper">
        <input
          v-model="search"
          placeholder="搜索用户..."
          @focus="showDropdown = true"
          @input="showDropdown = true"
        />
        <div v-if="showDropdown && filteredUsers.length" class="dropdown-list">
          <div
            v-for="u in filteredUsers"
            :key="u.id"
            class="dropdown-item"
            :class="{ selected: selectedUser?.id === u.id }"
            @click="selectUser(u)"
          >
            <span>{{ u.username }}</span>
            <span style="color:#888;font-size:11px">{{ u.role === 'admin' ? '管理员' : '用户' }}</span>
          </div>
        </div>
        <div v-if="showDropdown && search && !filteredUsers.length" class="dropdown-list">
          <div class="dropdown-item" style="color:#888">无匹配用户</div>
        </div>
      </div>

      <div v-if="selectedUser" class="selected-hint">
        已选择: <strong>{{ selectedUser.username }}</strong>
      </div>

      <p v-if="error" class="error">{{ error }}</p>
      <div class="modal-actions">
        <button class="btn-ghost" @click="$emit('close')">取消</button>
        <button class="btn btn-primary" @click="grant" :disabled="loading || !selectedUser">授权</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import api from '../api.js';

const props = defineProps({ agent: Object });
const emit = defineEmits(['close', 'done']);

const users = ref([]);
const search = ref('');
const selectedUser = ref(null);
const showDropdown = ref(false);
const loading = ref(false);
const error = ref('');

const filteredUsers = computed(() => {
  const q = search.value.toLowerCase().trim();
  if (!q) return users.value.filter(u => u.role !== 'admin');
  return users.value.filter(u => {
    if (u.role === 'admin') return false;
    return u.username.toLowerCase().includes(q);
  });
});

function selectUser(u) {
  selectedUser.value = u;
  search.value = u.username;
  showDropdown.value = false;
  error.value = '';
}

function closeDropdown(e) {
  if (!e.target.closest('.dropdown-wrapper')) {
    showDropdown.value = false;
  }
}

async function grant() {
  if (!selectedUser.value) return;
  loading.value = true;
  error.value = '';
  try {
    await api.post(`/agents/${props.agent.id}/grant`, { username: selectedUser.value.username });
    emit('done');
    emit('close');
  } catch (e) {
    error.value = e.response?.data?.detail || '授权失败';
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  const r = await api.get('/admin/users');
  users.value = r.data;
  document.addEventListener('click', closeDropdown);
});
</script>

<style scoped>
.dropdown-wrapper { position: relative; margin-bottom: 12px; }
.dropdown-list {
  position: absolute; top: 100%; left: 0; right: 0; max-height: 200px;
  overflow-y: auto; background: #16213e; border: 1px solid #333; border-radius: 4px;
  z-index: 10;
}
.dropdown-item {
  padding: 8px 12px; cursor: pointer; display: flex; justify-content: space-between;
  align-items: center; font-size: 13px;
}
.dropdown-item:hover, .dropdown-item.selected { background: #1a3a5c; }
.selected-hint { font-size: 13px; color: #4a90d9; margin-bottom: 12px; }
</style>
