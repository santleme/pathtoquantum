import { defineConfig } from 'vite';

// base relativa: funciona em GitHub Pages (subpath) e servido de qualquer pasta (ADR-001 §3.4).
export default defineConfig({ base: './' });
