import {test} from 'node:test'
import assert from 'node:assert/strict'
import {AxiosError} from 'axios'
import {createAdminApi,AdminApiError} from '../src/services/adminApi.ts'
import {createCustomerLookupStore} from '../src/pages/Customers/customerLookupStore.ts'
const ITEM={customer_id:'synthetic-id',email:'customer@example.test',account_status:'enabled' as const,activation_status:'pending' as const,created_at:'2026-01-01T10:00:00Z'}
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(yes=>{resolve=yes});return {promise,resolve}}

test('lookup uses existing credentialed client with JSON only, explicit CSRF and no query',async()=>{
 let calls=0
 const email=' Customer+alias@Example.test '
 const api=createAdminApi('https://api.example.test',async config=>{
  calls++;assert.equal(config.method,'post');assert.equal(config.url,'/admin/customers/lookup')
  assert.equal(config.baseURL,'https://api.example.test');assert.equal(config.withCredentials,true)
  assert.deepEqual(JSON.parse(config.data),{email});assert.equal(config.params,undefined)
  assert.equal(config.headers.get('Content-Type'),'application/json');assert.equal(config.headers.get('X-Admin-Request'),'1')
  assert.ok(!String(config.url).includes(email));assert.ok(!JSON.stringify(config.headers).includes(email))
  assert.equal(config.headers.has('Authorization'),false)
  return {data:{...ITEM,private:'synthetic-private'},status:200,statusText:'OK',headers:{},config}
 })
 assert.equal(calls,0);assert.deepEqual(await api.lookupCustomer(email),ITEM);assert.equal(calls,1)
})
for(const status of [400,401,403,404,409,413,415,422,503])test(`lookup HTTP ${status} is sanitized and never retried`,async()=>{
 let calls=0
 const api=createAdminApi('https://api.example.test',async config=>{calls++;throw new AxiosError('synthetic-private','ERR_BAD_RESPONSE',config,undefined,
  {data:{detail:'synthetic-private'},status,statusText:'private',headers:{},config})})
 await assert.rejects(api.lookupCustomer('customer@example.test'),(error:unknown)=>{
  assert.ok(error instanceof AdminApiError);assert.equal(error.status,status)
  assert.ok(!JSON.stringify(error).includes('synthetic-private'));assert.equal('config' in error,false);return true
 });assert.equal(calls,1)
})
test('lookup rejects malformed success and unsafe returned IDs',async()=>{
 for(const data of [null,{}, {...ITEM,customer_id:'../auth'}]){
  const api=createAdminApi('https://api.example.test',async config=>({data,status:200,statusText:'OK',headers:{},config}))
  await assert.rejects(api.lookupCustomer('customer@example.test'),AdminApiError)
 }
})
test('idle and editing never fetch; empty submission does not fetch',async()=>{
 let calls=0;const store=createCustomerLookupStore(()=>{},async()=>{calls++;return ITEM})
 assert.equal(store.getSnapshot().status,'idle');store.edit('   ');await store.search();assert.equal(calls,0)
 store.edit(' Customer+alias@Example.test ');assert.equal(calls,0);await store.search()
 assert.equal(store.getSnapshot().status,'found');assert.deepEqual(store.getSnapshot().customer,ITEM)
 store.edit('other@example.test');assert.equal(store.getSnapshot().customer,null)
})
test('submission deduplication and clear discard stale results',async()=>{
 let calls=0;const pending=deferred<typeof ITEM>()
 const store=createCustomerLookupStore(()=>{},async()=>{calls++;return pending.promise})
 store.edit('customer@example.test');const first=store.search();assert.equal(store.search(),first)
 assert.equal(store.getSnapshot().status,'loading');assert.equal(store.getSnapshot().customer,null)
 await Promise.resolve();assert.equal(calls,1);store.clear();pending.resolve(ITEM);await first
 assert.equal(store.getSnapshot().status,'idle');assert.equal(store.getSnapshot().email,'');assert.equal(store.getSnapshot().customer,null)
})
test('new email wins over stale response without mixed customers',async()=>{
 const old=deferred<typeof ITEM>();let calls=0
 const store=createCustomerLookupStore(()=>{},async()=>++calls===1?old.promise:{...ITEM,customer_id:'new'})
 store.edit('old@example.test');const first=store.search();await Promise.resolve()
 store.edit('new@example.test');await store.search();old.resolve(ITEM);await first
 assert.equal(store.getSnapshot().customer?.customer_id,'new')
})
for(const status of [400,401,403,404,409,413,415,422,503])test(`lookup state handles ${status} with no stale data`,async()=>{
 let unauthorized=0
 const store=createCustomerLookupStore(()=>{unauthorized++},async()=>{throw new AdminApiError(status===503?'unavailable':'unexpected_response',status)})
 store.edit('customer@example.test');await store.search()
 assert.equal(store.getSnapshot().customer,null);assert.equal(unauthorized,status===401?1:0)
 assert.equal(store.getSnapshot().status,status===404?'not_found':status===409?'ambiguous':'error')
 if(status===404){assert.equal(store.getSnapshot().message,'Nenhum cliente encontrado com esse e-mail.');assert.ok(!store.getSnapshot().message?.includes('compra'))}
 if(status===409)assert.match(store.getSnapshot().message!,/verificação administrativa/)
})
test('network/manual retry only on explicit submission, clear cleans personal data',async()=>{
 let calls=0;const store=createCustomerLookupStore(()=>{},async()=>{if(++calls===1)throw new AdminApiError('network');return ITEM})
 store.edit('customer@example.test');await store.search();assert.equal(calls,1)
 assert.equal(store.getSnapshot().message,'Não foi possível consultar o servidor.')
 await store.search();assert.equal(calls,2);assert.equal(store.getSnapshot().status,'found')
 store.clear();assert.equal(store.getSnapshot().customer,null);assert.equal(store.getSnapshot().email,'')
})
test('session invalidation can clear state before error handler publishes',async()=>{
 const store=createCustomerLookupStore(()=>store.clear(),async()=>{throw new AdminApiError('invalid_session',401)})
 store.edit('customer@example.test');await store.search();assert.equal(store.getSnapshot().status,'idle')
})
