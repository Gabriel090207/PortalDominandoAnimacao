import {test} from 'node:test'
import assert from 'node:assert/strict'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {createServer} from 'vite'
import {createCustomerActivationStore} from '../src/pages/Customers/customerActivationStore.ts'
import {AdminApiError} from '../src/services/adminApi.ts'

test('inline confirmation has labeled unchecked consent, cancel and no financial assurances',async()=>{
 const vite=await createServer({server:{middlewareMode:true,hmr:false,ws:false,watch:null}})
 try{
  const {default:View}=await vite.ssrLoadModule('/src/pages/Customers/CustomerActivation.tsx')
  let writes=0
  const store=createCustomerActivationStore('synthetic',{canActivate:()=>true,onUnauthorized:()=>{},refresh:async()=>{},
   activate:async()=>{writes++;return {customer_id:'synthetic',activation_status:'active',result:'activated'}}})
  const render=(available=true)=>renderToStaticMarkup(createElement(View,{activation:store,email:'customer@example.test',available}))
  assert.equal(render(false),'');assert.match(render(),/Ativar acesso/);assert.equal(writes,0)
  store.open();const form=render()
  for(const text of ['<form','<fieldset','Confirmar ativação manual','customer@example.test','Cancelar','Conferi as informações do comprador','type="checkbox"'])assert.ok(form.includes(text))
  assert.ok(!form.includes('checked=""'));assert.match(form,/type="submit"[^>]*disabled/)
  assert.ok(!form.includes('validade financeira'));assert.ok(!form.includes('R$'))
  store.consent(true);assert.ok(!render().match(/type="submit"[^>]*disabled/))
  store.cancel();assert.ok(!render().includes('type="checkbox"'));assert.equal(writes,0)
  store.open();assert.ok(!render().includes('checked=""'))
  store.consent(true);const request=store.submit();assert.match(render(),/Ativando acesso/);await request
  assert.match(render(false),/Acesso ativado com sucesso/)
  assert.ok(!render(false).includes('Confirmar ativação'))
 }finally{await vite.close()}
})

test('uncertain presentation offers explicit read, never false success or activation retry',async()=>{
 const vite=await createServer({server:{middlewareMode:true,hmr:false,ws:false,watch:null}})
 try{
  const {default:View}=await vite.ssrLoadModule('/src/pages/Customers/CustomerActivation.tsx')
  const store=createCustomerActivationStore('synthetic',{canActivate:()=>true,onUnauthorized:()=>{},refresh:async()=>{},
   activate:async()=>{throw new AdminApiError('unavailable',503)}})
  store.open();store.consent(true);await store.submit()
  const markup=renderToStaticMarkup(createElement(View,{activation:store,email:'customer@example.test',available:true}))
  assert.match(markup,/Não foi possível confirmar o resultado/);assert.match(markup,/Atualizar situação/)
  assert.match(markup,/role="alert"/);assert.ok(!markup.includes('Ativar acesso'));assert.ok(!markup.includes('sucesso'))
 }finally{await vite.close()}
})
