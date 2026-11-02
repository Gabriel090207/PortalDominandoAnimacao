import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'node:fs'

export default defineConfig(({ command }) => {
  if (command !== 'serve' || process.env.ADMIN_LOCAL_ENABLED !== 'true')
    return { plugins: [react()] }
  const cert = process.env.ADMIN_LOCAL_TLS_CERT
  const key = process.env.ADMIN_LOCAL_TLS_KEY
  if (process.env.ADMIN_LOCAL_ENVIRONMENT !== 'development' || !cert || !key ||
    process.env.VITE_API_URL !== 'https://localhost:8443')
    throw new Error('Invalid isolated local Admin configuration.')
  return {
    plugins: [react()],
    server: {
      host: '127.0.0.1', port: 5174, strictPort: true,
      https: { cert: readFileSync(cert), key: readFileSync(key) },
      allowedHosts: ['localhost'], cors: false,
    },
  }
})
