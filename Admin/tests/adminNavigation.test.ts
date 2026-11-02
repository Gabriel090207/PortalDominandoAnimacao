import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {createServer} from 'vite'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {MemoryRouter} from 'react-router-dom'
import {createSessionStore} from '../src/session/sessionStore.ts'
import {AdminApiError} from '../src/services/adminApi.ts'

const session={admin_id:'private-admin-id',email:'private-admin@example.test',role:'owner' as const,permissions:['read_customers' as const]}

test('real pending verification shows loading; completion opens customer home without extra session calls',async()=>{
 const vite=await createServer({server:{middlewareMode:true,hmr:false,ws:false,watch:null}})
 try{
  const {SessionRoutes}=await vite.ssrLoadModule('/src/App.tsx')
  let queries=0,resolve!:(value:typeof session)=>void
  const pending=new Promise<typeof session>(yes=>{resolve=yes})
  const store=createSessionStore({login:async()=>({admin_id:session.admin_id}),getSession:async()=>{queries++;return pending},logout:async()=>({success:true})})
  const render=()=>renderToStaticMarkup(createElement(MemoryRouter,{initialEntries:['/clientes']},createElement(SessionRoutes,{store})))
  const verifying=store.verify()
  await Promise.resolve()
  assert.match(render(),/Preparando seu painel/)
  assert.match(render(),/role="status"/)
  assert.ok(!render().includes('Listagem de clientes'))
  assert.equal(queries,1)
  resolve(session);await verifying
  const home=render()
  assert.match(home,/Gerenciamento de clientes/)
  assert.match(home,/Buscar cliente/)
  assert.match(home,/Até 20 clientes por consulta/)
  assert.match(home,/Anterior/);assert.match(home,/Próxima/)
  assert.ok(!home.includes('Preparando seu painel'))
  assert.ok(!home.includes(session.admin_id));assert.ok(!home.includes(session.email))
  assert.equal(queries,1)
  await store.logout()
  assert.ok(!render().includes('Listagem de clientes'))
 }finally{await vite.close()}
})

test('verification failure leaves loading and preserves the safe error screen',async()=>{
 const vite=await createServer({server:{middlewareMode:true,hmr:false,ws:false,watch:null}})
 try{
  const {SessionRoutes}=await vite.ssrLoadModule('/src/App.tsx')
  let queries=0
  const store=createSessionStore({login:async()=>({admin_id:session.admin_id}),getSession:async()=>{queries++;throw new AdminApiError('network')},logout:async()=>({success:true})})
  await store.verify()
  const html=renderToStaticMarkup(createElement(MemoryRouter,{initialEntries:['/clientes']},createElement(SessionRoutes,{store})))
  assert.match(html,/Não foi possível confirmar o acesso/)
  assert.ok(!html.includes('Preparando seu painel'));assert.ok(!html.includes('Listagem de clientes'))
  assert.equal(queries,1)
 }finally{await vite.close()}
})

test('home/legacy routes keep authentication and canonical customer destination; loading is presentation only',async()=>{
 const source=await readFile('src/App.tsx','utf8')
 assert.match(source,/path="\/" element=\{authenticated \? <Navigate to="\/clientes" replace/)
 assert.match(source,/path="\/painel" element=\{authenticated \? <Navigate to="\/clientes" replace\/> : <Navigate to="\/" replace/)
 assert.ok(!source.includes('<Panel'))
 const login=await readFile('src/pages/Login/Login.tsx','utf8')
 assert.match(login,/if \(pending\) return <AdminLoading/)
 const loading=await readFile('src/components/AdminLoading/AdminLoading.tsx','utf8')
 assert.ok(!/setTimeout|setInterval|fetch\(|useEffect/.test(loading))
 assert.match(loading,/session-verification-error__symbol/)
 const styles=await readFile('src/components/SessionVerificationError/SessionVerificationError.css','utf8')
 assert.match(styles,/@media\(prefers-reduced-motion:reduce\)/)
})
