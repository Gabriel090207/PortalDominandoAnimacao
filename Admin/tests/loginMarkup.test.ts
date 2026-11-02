import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

test('initial React markup has accessible fields and no fictitious authenticated state', async () => {
  const vite = await createServer({ server: { middlewareMode: true, hmr: false, ws: false, watch: null } })
  try {
    const { default: Login } = await vite.ssrLoadModule('/src/pages/Login/Login.tsx')
    const markup = renderToStaticMarkup(createElement(Login))
    assert.match(markup, /Área administrativa/)
    assert.match(markup, /Dominando <strong>Animação<\/strong>/)
    assert.ok(markup.indexOf('</header>') < markup.indexOf('<section class="login-card"'))
    assert.match(markup, /class="session-verification-error__background" aria-hidden="true"/)
    assert.match(markup, /Bem-vindo de volta/)
    assert.match(markup, /Entrar no Admin/)
    assert.ok(!markup.includes('class="spinner"'))
    assert.match(markup, /label for="admin-email"/)
    assert.match(markup, /label for="admin-password"/)
    assert.match(markup, /type="password"/)
    assert.match(markup, /autoComplete="username"/)
    assert.match(markup, /autoComplete="current-password"/)
    assert.match(markup, /aria-label="Mostrar senha"/)
    assert.match(markup, /aria-pressed="false"/)
    assert.match(markup, /aria-controls="admin-password"/)
    assert.match(markup, /class="visibility-button"[^>]*><svg[^>]*aria-hidden="true"/)
    assert.equal((markup.match(/class="input-icon"/g) ?? []).length, 2)
    assert.match(markup, /aria-live="polite"/)
    assert.match(markup, /noValidate=""/)
    assert.ok(!markup.includes('Sessão administrativa confirmada.'))
    assert.ok(!markup.includes('Esqueci minha senha'))
  } finally { await vite.close() }
})
