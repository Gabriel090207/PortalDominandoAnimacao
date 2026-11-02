import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import config from '../vite.config.ts'

test('isolated local Vite mode is opt-in, HTTPS, loopback and strict-port', () => {
  assert.equal(typeof config, 'function')
  if (typeof config !== 'function') throw new Error('Expected configuration factory')
  const previous = { ...process.env }
  const directory = mkdtempSync(join(tmpdir(), 'admin-local-config-'))
  try {
    delete process.env.ADMIN_LOCAL_ENABLED
    assert.deepEqual(Object.keys(config({ command: 'serve', mode: 'development' })), ['plugins'])
    process.env.ADMIN_LOCAL_ENABLED = 'true'
    process.env.ADMIN_LOCAL_ENVIRONMENT = 'production'
    assert.throws(() => config({ command: 'serve', mode: 'development' }))
    process.env.ADMIN_LOCAL_ENVIRONMENT = 'development'
    process.env.VITE_API_URL = 'https://localhost:8443'
    process.env.ADMIN_LOCAL_TLS_CERT = join(directory, 'cert')
    process.env.ADMIN_LOCAL_TLS_KEY = join(directory, 'key')
    writeFileSync(process.env.ADMIN_LOCAL_TLS_CERT, 'synthetic certificate fixture')
    writeFileSync(process.env.ADMIN_LOCAL_TLS_KEY, 'synthetic key fixture')
    const local = config({ command: 'serve', mode: 'development' })
    assert.ok('server' in local)
    assert.equal(local.server?.host, '127.0.0.1')
    assert.equal(local.server?.port, 5174)
    assert.equal(local.server?.strictPort, true)
    assert.equal(local.server?.cors, false)
    assert.ok(local.server?.https)
    assert.deepEqual(Object.keys(config({ command: 'build', mode: 'production' })), ['plugins'])
  } finally {
    process.env = previous
    rmSync(directory, { recursive: true })
  }
})
