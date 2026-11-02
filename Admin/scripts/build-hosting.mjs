import { build } from 'vite'
import { execFileSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import { isIP } from 'node:net'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')

export function validateHostingApi(value) {
  try {
    const url = new URL(value)
    const host = url.hostname.toLowerCase()
    if (typeof value !== 'string' || value !== value.trim() || url.protocol !== 'https:' ||
        url.username || url.password || url.search || url.hash || url.pathname !== '/' ||
        !host.includes('.') || host.endsWith('.') || isIP(host) || host.includes(':') ||
        host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local')) throw new Error()
    return url.origin
  } catch { throw new Error('Configure an explicit HTTPS API origin with a DNS hostname for the hosting build.') }
}

export function hostingOptions(api) {
  return {
    root, configFile: resolve(root, 'vite.config.ts'), mode: 'production',
    // No .env files or arbitrary process VITE_* variables in this artifact.
    envDir: false, envPrefix: [], base: '/',
    define: { 'import.meta.env.VITE_API_URL': JSON.stringify(validateHostingApi(api)) },
    build: { outDir: resolve(root, 'dist-hosting'), emptyOutDir: true, sourcemap: false },
  }
}

async function main() {
  const api = validateHostingApi(process.env.VITE_API_URL)
  execFileSync(process.execPath, [resolve(root, 'node_modules/typescript/bin/tsc'), '-b'], { cwd: root, stdio: 'inherit' })
  await build(hostingOptions(api))
  const template = readFileSync(resolve(root, 'hosting/admin.htaccess.template'), 'utf8')
  writeFileSync(resolve(root, 'dist-hosting/.htaccess'), template.replaceAll('__ADMIN_API_ORIGIN__', api))
  console.log('Static Admin artifact prepared in dist-hosting. Not published; hosting and API approval still required.')
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(() => {
    console.error('Admin hosting build failed. Check the public API origin and local build configuration.')
    process.exitCode = 1
  })
}
