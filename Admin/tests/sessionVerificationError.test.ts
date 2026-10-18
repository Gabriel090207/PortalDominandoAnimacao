import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {MemoryRouter} from 'react-router-dom'
import {createServer} from 'vite'
import {createSessionStore} from '../src/session/sessionStore.ts'
import {AdminApiError} from '../src/services/adminApi.ts'


test('error presentation keeps semantics, retry and decorative backdrop without private content',async()=>{
 const vite=await createServer({server:{middlewareMode:true,hmr:false,ws:false,watch:null}})
 try{
  const {SessionRoutes}=await vite.ssrLoadModule('/src/App.tsx')
  const store=createSessionStore({login:async()=>{throw Error('login must not run')},logout:async()=>{throw Error('logout must not run')},getSession:async()=>{throw new AdminApiError('network')}})
  await store.verify()
  for(const path of ['/painel','/clientes','/clientes/private-customer']){
   const html=renderToStaticMarkup(createElement(MemoryRouter,{initialEntries:[path]},createElement(SessionRoutes,{store})))
   for(const text of ['Não foi possível confirmar o acesso','Isso não significa que ela expirou ou que houve logout','Consultar sessão novamente','session-verification-error__card','role="alert"','aria-hidden="true"'])assert.ok(html.includes(text))
   for(const privateText of ['Ficha do cliente','Listagem de clientes','Painel administrativo','private@example.test'])assert.ok(!html.includes(privateText))
   assert.match(html,/<h1 id="session-verification-title"/)
  }
  assert.equal(store.getSnapshot().status,'error')
 }finally{await vite.close()}
})


test('original manual retry queries session only and preserves checking state before confirmation',async()=>{
 const vite=await createServer({server:{middlewareMode:true,hmr:false,ws:false,watch:null}})
 try{
  const {SessionRoutes}=await vite.ssrLoadModule('/src/App.tsx')
  let queries=0,reject!:(reason:unknown)=>void
  const pending=new Promise<never>((_,no)=>{reject=no})
  const store=createSessionStore({login:async()=>{throw Error('unexpected login')},logout:async()=>{throw Error('unexpected logout')},getSession:async()=>{queries++;if(queries===1)throw new AdminApiError('unavailable',503);return pending}})
  const render=()=>renderToStaticMarkup(createElement(MemoryRouter,{initialEntries:['/clientes/private']},createElement(SessionRoutes,{store})))
  await store.verify();assert.equal(queries,1)
  render();render();await Promise.resolve();assert.equal(queries,1)
  // Invoke the same store method retained by the button. SSR does not dispatch DOM clicks.
  const retry=store.verify();assert.equal(store.verify(),retry)
  assert.equal(store.getSnapshot().status,'checking');assert.match(render(),/Verificando sessão/)
  assert.ok(!render().includes('Ficha do cliente'))
  await Promise.resolve();assert.equal(queries,2)
  reject(new AdminApiError('network'));await retry
  assert.equal(store.getSnapshot().status,'error');assert.ok(!render().includes('Ficha do cliente'))
  // Source contract guards the unchanged binding; presentation does not own retry logic.
  const source=await readFile('src/App.tsx','utf8')
  assert.match(source,/SessionVerificationError message=\{state.message\}><button type="button" onClick=\{\(\) => void store.verify\(\)\}/)
 }finally{await vite.close()}
})


test('scoped styling provides balanced wrapping, touch targets, responsive layout and reduced motion',async()=>{
 const css=await readFile('src/components/SessionVerificationError/SessionVerificationError.css','utf8')
 for(const rule of ['text-wrap:balance','text-wrap:pretty','clamp(','max-width:100%','min-height:52px',':focus-visible',':disabled','@media(max-width:480px)','@media(prefers-reduced-motion:reduce)','animation:none','transition:none','pointer-events:none'])assert.ok(css.includes(rule))
 assert.ok(!css.includes('@import'));assert.ok(!css.includes('url('))
 assert.ok(!css.includes('.login-card {'))
})


test('refinement keeps desktop title on one line with a readable mobile fallback',async()=>{
 const css=await readFile('src/components/SessionVerificationError/SessionVerificationError.css','utf8')
 assert.match(css,/h1 \{[^}]*color:#ffffff;[^}]*font-size:clamp\(1.25rem,2.5vw,1.5rem\)/)
 assert.match(css,/h1 \{max-width:100%;/)
 assert.ok(!css.includes('white-space:nowrap'))
 assert.match(css,/__message \{max-width:68ch;[^}]*font-size:\.8rem;line-height:1.65;text-wrap:balance/)
 assert.match(css,/__content \{[^}]*max-width:536px/)
 assert.match(css,/__card \{[^}]*padding:32px 24px/)
 const component=await readFile('src/components/SessionVerificationError/SessionVerificationError.tsx','utf8')
 assert.ok(!component.includes('<br'))
})

test('icon rotates using CSS alone and reduced motion disables decorative animations',async()=>{
 const css=await readFile('src/components/SessionVerificationError/SessionVerificationError.css','utf8')
 assert.match(css,/__symbol svg \{[^}]*animation:session-verification-spin 2\.5s linear infinite/)
 assert.match(css,/@keyframes session-verification-spin \{to\{transform:rotate\(360deg\);/)
 assert.match(css,/@media\(prefers-reduced-motion:reduce\) \{[^]*__symbol svg \{animation:none;/)
 assert.match(css,/font-size:1rem;font-weight:750/)
 assert.match(css,/background:linear-gradient\(135deg,rgba\(0,224,255,\.94\),rgba\(0,151,255,\.96\)\)/)
 assert.match(css,/filter:brightness\(1\.06\)/)
 const component=await readFile('src/components/SessionVerificationError/SessionVerificationError.tsx','utf8')
 assert.ok(!/setInterval|setTimeout|requestAnimationFrame/.test(component))
})
