import {test} from 'node:test'
import assert from 'node:assert/strict'
import {createServer} from 'vite'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {MemoryRouter} from 'react-router-dom'
import {createCustomerLookupStore} from '../src/pages/Customers/customerLookupStore.ts'
import {createSessionStore} from '../src/session/sessionStore.ts'
import {AdminApiError} from '../src/services/adminApi.ts'
import type {AdminSession} from '../src/services/adminApi.ts'
const ITEM={customer_id:'real synthetic-id',email:'customer@example.test',account_status:'enabled' as const,activation_status:'pending' as const,created_at:'2026-01-01T10:00:00Z'}

test('semantic lookup form and synthetic states render with existing customer navigation',async()=>{
 const vite=await createServer({server:{middlewareMode:true,hmr:false,ws:false,watch:null}})
 try{
  const {CustomerLookupForm}=await vite.ssrLoadModule('/src/pages/Customers/CustomerLookup.tsx')
  let calls=0
  const lookup=createCustomerLookupStore(()=>{},async()=>{calls++;return ITEM})
  const render=()=>renderToStaticMarkup(createElement(MemoryRouter,null,createElement(CustomerLookupForm,{lookup})))
  const initial=render();assert.equal(calls,0)
  for(const value of ['Buscar cliente','E-mail utilizado na compra','<form','noValidate','type="submit"','Pesquisar','for="customer-search-email"'])assert.ok(initial.includes(value))
  assert.ok(!initial.includes('customer@example.test'))
  lookup.edit('customer@example.test');const pending=lookup.search()
  assert.match(render(),/Pesquisando cliente/);await pending
  const found=render()
  for(const value of ['Cliente encontrado.','customer@example.test','Habilitada','Pendente','10:00 UTC','Ver cliente','/clientes/real%20synthetic-id'])assert.ok(found.includes(value))
  assert.ok(!found.includes('Ativar'))
  lookup.clear();assert.ok(!render().includes('customer@example.test'))
  for(const status of [404,409,503]){
   const failed=createCustomerLookupStore(()=>{},async()=>{throw new AdminApiError(status===503?'unavailable':'unexpected_response',status)})
   failed.edit('customer@example.test');await failed.search()
   const markup=renderToStaticMarkup(createElement(MemoryRouter,null,createElement(CustomerLookupForm,{lookup:failed})))
   assert.ok(!markup.includes('Ver cliente'))
   assert.match(markup,status===404?/Nenhum cliente encontrado/:status===409?/verificação administrativa/:/indisponível/)
  }
 }finally{await vite.close()}
})

test('route gates lookup for missing/unverified/unavailable sessions and permission, both roles can see form',async()=>{
 const vite=await createServer({server:{middlewareMode:true,hmr:false,ws:false,watch:null}})
 try{
  const {SessionRoutes}=await vite.ssrLoadModule('/src/App.tsx')
  for(const mode of ['owner','operator','denied','absent','unavailable']){
   const session:AdminSession={admin_id:'synthetic-admin',email:'admin@example.test',role:mode==='owner'?'owner':'operator',permissions:mode==='denied'?[]:['read_customers']}
   const store=createSessionStore({async getSession(){if(mode==='absent')throw new AdminApiError('invalid_session',401);if(mode==='unavailable')throw new AdminApiError('unavailable',503);return session},async login(){return {admin_id:'synthetic-admin'}},async logout(){return {success:true}}})
   const render=()=>renderToStaticMarkup(createElement(MemoryRouter,{initialEntries:['/clientes']},createElement(SessionRoutes,{store})))
   assert.ok(!render().includes('Buscar cliente'));await store.verify()
   assert.equal(render().includes('Buscar cliente'),mode==='owner'||mode==='operator')
  }
 }finally{await vite.close()}
})
