import { createRouter, createWebHashHistory } from 'vue-router';
import LoginView from './views/LoginView.vue';
import AgentListView from './views/AgentListView.vue';
import AgentDetailView from './views/AgentDetailView.vue';
import UserListView from './views/UserListView.vue';
import UserDetailView from './views/UserDetailView.vue';
import ModelConfigListView from './views/ModelConfigListView.vue';
import VoicePoolView from './views/VoicePoolView.vue';

const routes = [
  { path: '/login', component: LoginView },
  { path: '/', redirect: '/agents' },
  { path: '/agents', component: AgentListView },
  { path: '/agents/:id', component: AgentDetailView, props: true },
  { path: '/users', component: UserListView },
  { path: '/users/:username', component: UserDetailView, props: true },
  { path: '/model-configs', component: ModelConfigListView },
  { path: '/voices', component: VoicePoolView },
];

const router = createRouter({ history: createWebHashHistory(), routes });

router.beforeEach((to) => {
  const token = localStorage.getItem('admin_token');
  if (to.path !== '/login' && !token) return '/login';
});

export default router;
