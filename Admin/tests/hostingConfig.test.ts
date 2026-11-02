import test from 'node:test'
import assert from 'node:assert/strict'
// JS build tooling is intentionally separate from the browser/TypeScript app.
import { validateHostingApi, hostingOptions } from '../scripts/build-hosting.mjs'

test('hosting API is explicit HTTPS, without credentials or local addresses', () => {
  assert.equal(validateHostingApi('https://api.example.invalid/'), 'https://api.example.invalid')
  for (const value of [undefined, '', 'http://api.example.invalid', 'https://localhost:8443',
    'https://127.0.0.1', 'https://[::1]', 'https://service.local', 'https://api.example.invalid/path',
    'https://user:synthetic@api.example.invalid', 'https://api.example.invalid?secret=x',
    'https://api.example.invalid#x', ' https://api.example.invalid']) {
    assert.throws(() => validateHostingApi(value))
  }
})

test('hosting artifact isolates env loading, output and API definition', () => {
  const options = hostingOptions('https://api.example.invalid')
  assert.equal(options.envDir, false)
  assert.deepEqual(options.envPrefix, [])
  assert.equal(options.base, '/')
  assert.equal(options.build.sourcemap, false)
  assert.ok(options.build.outDir.endsWith('/dist-hosting'))
  assert.equal(options.define['import.meta.env.VITE_API_URL'], '"https://api.example.invalid"')
})
