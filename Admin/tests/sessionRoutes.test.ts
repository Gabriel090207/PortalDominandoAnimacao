import {test} from 'node:test'
import assert from 'node:assert/strict'
import {createServer} from 'vite'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {MemoryRouter} from 'react-router-dom'
import {createSessionStore} from '../src/session/sessionStore.ts'
import {AdminApiError} from '../src/services/adminApi.ts'
import type {AdminSession} from '../src/services/adminApi.ts'
const SESSION: AdminSession = {admin_id:'synthetic-admin',email:'admin@example.test',role:'operator',permissions:['read_customers']}

test('real route tree gates direct /painel without protected content flash',async()=>{
 const vite=await createServer({server:{middlewareMode:true,hmr:false,ws:false,watch:null}})
 try{
  const {SessionRoutes}=await vite.ssrLoadModule('/src/App.tsx')
  const service={async login(){return {admin_id:'synthetic-admin'}},async getSession(){return SESSION},async logout(){return {success:true as const}}}
  const store=createSessionStore(service)
  const render=(path:string)=>renderToStaticMarkup(createElement(MemoryRouter,{initialEntries:[path]},createElement(SessionRoutes,{store})))
  const loading=render('/painel')
  assert.match(render('/clientes/customer-a'),/Verificando sessão/)
  assert.match(loading,/Verificando sessão/)
  assert.ok(!loading.includes('Painel administrativo'))
  await store.verify()
  const authenticated=render('/painel')
  assert.match(authenticated,/Painel administrativo/)
  assert.match(authenticated,/admin@example.test/)
  assert.match(authenticated,/Operador/)
  assert.match(authenticated,/Sair/)
  assert.match(authenticated,/href="\/clientes"/)
  assert.match(render('/clientes'),/Consultando clientes/)
  assert.match(render('/clientes/customer-a'),/Consultando cliente/)
  assert.ok(!render('/clientes/customer-a').includes('customer@example.test'))
  assert.ok(!render('/clientes').includes('customer@example.test'))
  store.handleUnauthorized(new AdminApiError('invalid_session',401))
  assert.ok(!render('/painel').includes('Painel administrativo'))
  assert.match(render('/'),/Bem-vindo de volta/)
  assert.ok(!render('/clientes').includes('Listagem de clientes'))
  assert.ok(!render('/clientes/customer-a').includes('Ficha do cliente'))
  const restricted=createSessionStore({...service,async getSession(){return {...SESSION,permissions:[]}}})
  await restricted.verify()
  const denied=renderToStaticMarkup(createElement(MemoryRouter,{initialEntries:['/clientes']},createElement(SessionRoutes,{store:restricted})))
  assert.match(denied,/Acesso não autorizado/)
  const detailDenied=renderToStaticMarkup(createElement(MemoryRouter,{initialEntries:['/clientes/customer-a']},createElement(SessionRoutes,{store:restricted})))
  assert.match(detailDenied,/Acesso não autorizado/)
  assert.ok(!denied.includes('Listagem de clientes'))
  const {CustomersList}=await vite.ssrLoadModule('/src/pages/Customers/Customers.tsx')
  const list=renderToStaticMarkup(createElement(MemoryRouter,null,createElement(CustomersList,{state:{status:'ready',items:[{customer_id:'customer-a',email:'customer@example.test',account_status:'blocked',activation_status:'suspended',created_at:'2026-01-01T10:00:00Z'}],nextCursor:null,canPrevious:false}})))
  assert.match(list,/href="\/clientes\/customer-a"/)
  const {CustomerFacts}=await vite.ssrLoadModule('/src/pages/Customers/CustomerDetail.tsx')
  const facts=renderToStaticMarkup(createElement(CustomerFacts,{customer:{customer_id:'synthetic',email:'synthetic@example.test',account_status:'blocked',activation_status:'suspended',created_at:'2026-01-01T10:00:00Z'}}))
  for(const expected of ['synthetic@example.test','Bloqueada','Suspensa','10:00 UTC'])assert.ok(facts.includes(expected))
  const fallback=renderToStaticMarkup(createElement(CustomerFacts,{customer:{customer_id:'x'.repeat(1500),email:'long'.repeat(100)+'@example.test',account_status:'unknown',activation_status:'unknown',created_at:''}}))
  assert.match(fallback,/Estado não reconhecido/)
  assert.match(fallback,/Data indisponível/)
  assert.ok(!facts.includes('Assinatura'))
  const {readFile}=await import('node:fs/promises')
  const css=await readFile('src/pages/Customers/Customers.css','utf8')
  assert.match(css,/customer-facts dd[^}]*overflow-wrap:anywhere/)
  assert.match(css,/max-width:480px/)

  for(const expected of ['customer-a','customer@example.test','Bloqueada','Suspensa','01/01/2026','10:00 UTC'])assert.ok(list.includes(expected))
  const unavailable=createSessionStore({...service,async getSession(){throw new AdminApiError('unavailable',503)}})
  await unavailable.verify()
  const failure=renderToStaticMarkup(createElement(MemoryRouter,{initialEntries:['/painel']},createElement(SessionRoutes,{store:unavailable})))
  assert.match(failure,/Consultar sessão novamente/)
  const detailFailure=renderToStaticMarkup(createElement(MemoryRouter,{initialEntries:['/clientes/customer-a']},createElement(SessionRoutes,{store:unavailable})))
  assert.ok(!detailFailure.includes('Ficha do cliente'))
  assert.ok(!failure.includes('Painel administrativo'))
 }finally{await vite.close()}
})
