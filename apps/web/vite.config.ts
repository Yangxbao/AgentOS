import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // 开发态同源代理：前端 API 基址为空（见 .env.development），浏览器只与 5173 同源通信，
    // 由 Vite 转发 /api 到后端。这是 LocalGuard 期望的同源部署拓扑——不要改成浏览器直连后端。
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true, // 后端 Host 校验只看主机名（localhost/127.0.0.1 均允许），true/false 都能过
      },
    },
  },
})
