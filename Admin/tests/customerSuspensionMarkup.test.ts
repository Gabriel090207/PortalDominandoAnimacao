import {test} from 'node:test'
import assert from 'node:assert/strict'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {createServer} from 'vite'
import {createCustomerSuspensionStore} from '../src/pages/Customers/customerSuspensionStore.ts'
import {AdminApiError} from '../src/services/adminApi.ts'

test('inline confirmation has labeled unchecked consent, cancel and no financial assurances',async()=>{
 const vite=await createServer({server:{middlewareMode:true,hmr:false,ws:false,watch:null}})
 try{
  const {default:View}=await vite.ssrLoadModule('/src/pages/Customers/CustomerSuspension.tsx')
  let writes=0
  const store=createCustomerSuspensionStore('synthetic',{canSuspend:()=>true,onUnauthorized:()=>{},refresh:async()=>{},
   suspend:async()=>{writes++;return {customer_id:'synthetic',activation_status:'suspended',result:'suspended'}}})
  const render=(available=true)=>renderToStaticMarkup(createElement(View,{suspension:store,email:'customer@example.test',available}))
  assert.equal(render(false),'');assert.match(render(),/Suspender acesso/);assert.equal(writes,0)
  store.open();const form=render()
  for(const text of ['<form','<fieldset','Suspender acesso do cliente','customer@example.test','Cancelar','Confirmo que desejo suspender o acesso deste cliente.','type="checkbox"'])assert.ok(form.includes(text))
  assert.ok(!form.includes('checked=""'));assert.match(form,/type="submit"[^>]*disabled/)
  assert.match(form,/temporariamente o acesso ao portal/);assert.match(form,/não cancela a assinatura na Kirvano/);assert.ok(!form.includes('validade financeira'));assert.ok(!form.includes('R$'))
  store.consent(true);assert.ok(!render().match(/type="submit"[^>]*disabled/))
  store.cancel();assert.ok(!render().includes('type="checkbox"'));assert.equal(writes,0)
  store.open();assert.ok(!render().includes('checked=""'))
  store.consent(true);const request=store.submit();assert.match(render(),/Suspendendo acesso/);await request
  assert.match(render(false),/Acesso suspenso com sucesso/)
  assert.ok(!render(false).includes('Confirmar suspensão'))
 }finally{await vite.close()}
})

test('uncertain presentation offers explicit read, never false success or activation retry',async()=>{
 const vite=await createServer({server:{middlewareMode:true,hmr:false,ws:false,watch:null}})
 try{
  const {default:View}=await vite.ssrLoadModule('/src/pages/Customers/CustomerSuspension.tsx')
  const store=createCustomerSuspensionStore('synthetic',{canSuspend:()=>true,onUnauthorized:()=>{},refresh:async()=>{},
   suspend:async()=>{throw new AdminApiError('unavailable',503)}})
  store.open();store.consent(true);await store.submit()
  const markup=renderToStaticMarkup(createElement(View,{suspension:store,email:'customer@example.test',available:true}))
  assert.match(markup,/Não foi possível confirmar o resultado/);assert.match(markup,/Atualizar situação/)
  assert.match(markup,/role="alert"/);assert.ok(!markup.includes('Suspender acesso'));assert.ok(!markup.includes('sucesso'))
 }finally{await vite.close()}
})
