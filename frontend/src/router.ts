import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'

export const routes = [
  { path: '/', redirect: '/mix' },
  { path: '/mix', name: 'mix', component: () => import('./views/MixView.vue') },
  { path: '/library', name: 'library', component: () => import('./views/LibraryView.vue') },
  { path: '/models', name: 'models', component: () => import('./views/ModelsView.vue') },
  { path: '/settings', name: 'settings', component: () => import('./views/SettingsView.vue') },
]

export function makeRouter(history: RouterHistory = createWebHistory()) {
  return createRouter({ history, routes })
}
