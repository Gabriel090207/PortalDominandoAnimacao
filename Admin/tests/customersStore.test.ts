import {test} from 'node:test'
import assert from 'node:assert/strict'
import {createCustomersStore} from '../src/pages/Customers/customersStore.ts'
import {accountLabel,activationLabel,registrationDate} from '../src/pages/Customers/customerDisplay.ts'
import {AdminApiError} from '../src/services/adminApi.ts'
import type {AdminCustomerPage,CustomerQuery} from '../src/services/adminApi.ts'
const ITEM={customer_id:'synthetic-id',email:'customer@example.test',account_status:'enabled' as const,activation_status:'pending' as const,created_at:'2026-01-01T10:00:00Z'}
const PAGE:AdminCustomerPage={items:[ITEM],next_cursor:'YQ'}
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(yes=>{resolve=yes});return {promise,resolve}}

test('initial load is bounded, shared across StrictMode effects and shows loading without old data',async()=>{
 let calls=0;const pending=deferred<AdminCustomerPage>()
 const store=createCustomersStore(()=>{},async query=>{calls++;assert.deepEqual(query,{limit:20});return pending.promise})
 const first=store.loadInitial(),second=store.loadInitial();assert.equal(first,second)
 assert.equal(store.getSnapshot().status,'loading');assert.deepEqual(store.getSnapshot().items,[])
 await Promise.resolve();assert.equal(calls,1);pending.resolve(PAGE);await first
 assert.deepEqual(store.getSnapshot().items,[ITEM])
})
test('next and previous use returned cursors, no totals, stop at last page',async()=>{
 const queries:CustomerQuery[]=[]
 const store=createCustomersStore(()=>{},async query=>{queries.push(query);return query.cursor?{items:[],next_cursor:null}:PAGE})
 await store.loadInitial();await store.next();assert.equal(store.getSnapshot().canPrevious,true)
 await store.next();assert.equal(queries.length,2)
 await store.previous();assert.deepEqual(queries,[{limit:20},{limit:20,cursor:'YQ'},{limit:20}])
 assert.equal(store.getSnapshot().canPrevious,false)
})
test('old replies cannot restore cleared session/customer data',async()=>{
 const old=deferred<AdminCustomerPage>()
 const store=createCustomersStore(()=>{},()=>old.promise)
 const request=store.loadInitial();await Promise.resolve();store.clear()
 old.resolve(PAGE);await request
 assert.equal(store.getSnapshot().status,'idle');assert.deepEqual(store.getSnapshot().items,[])
})
test('newer session query wins over previous stale response',async()=>{
 const old=deferred<AdminCustomerPage>();let calls=0
 const store=createCustomersStore(()=>{},async()=>++calls===1?old.promise:{items:[],next_cursor:null})
 const first=store.loadInitial();await Promise.resolve();store.clear();await store.loadInitial()
 old.resolve(PAGE);await first
 assert.equal(store.getSnapshot().status,'ready');assert.deepEqual(store.getSnapshot().items,[])
})
for(const status of [400,401,403,422,503]){
 test(`safe handling of ${status}`,async()=>{
  let unauthorized=0
  const store=createCustomersStore(()=>{unauthorized++},async()=>{throw new AdminApiError(status===403?'forbidden':status===401?'invalid_session':status===503?'unavailable':'invalid_request',status)})
  await store.loadInitial();assert.deepEqual(store.getSnapshot().items,[])
  assert.equal(unauthorized,status===401?1:0)
  assert.equal(store.getSnapshot().status,status===403?'forbidden':'error')
 })
}
test('manual retry for failed next page retries that cursor',async()=>{
 let calls=0;const queries:CustomerQuery[]=[]
 const store=createCustomersStore(()=>{},async query=>{queries.push(query);if(++calls===2)throw new AdminApiError('network');return query.cursor?{items:[],next_cursor:null}:PAGE})
 await store.loadInitial();await store.next();assert.equal(store.getSnapshot().status,'error')
 await store.retry();assert.deepEqual(queries[2],{limit:20,cursor:'YQ'});assert.equal(store.getSnapshot().status,'ready')
})
test('safe unknown status and invalid/zoneless date display',()=>{
 assert.equal(accountLabel('enabled'),'Habilitada');assert.equal(accountLabel('blocked'),'Bloqueada')
 assert.equal(activationLabel('pending'),'Pendente');assert.equal(activationLabel('active'),'Ativa');assert.equal(activationLabel('suspended'),'Suspensa')
 for(const value of ['unknown','toString'])assert.equal(accountLabel(value),'Estado não reconhecido')
 for(const value of [null,'bad','2026-01-01T10:00:00','2026-02-30T10:00:00Z'])assert.equal(registrationDate(value),'Data indisponível')
 assert.match(registrationDate('2026-01-01T10:00:00-03:00'),/13:00 UTC/)
})
