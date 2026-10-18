import {test} from 'node:test'
import assert from 'node:assert/strict'
import {AxiosError} from 'axios'
import {createAdminApi,AdminApiError} from '../src/services/adminApi.ts'
import {createCustomerDetailStore} from '../src/pages/Customers/customerDetailStore.ts'
const ITEM={customer_id:'synthetic-id',email:'customer@example.test',account_status:'enabled' as const,activation_status:'pending' as const,created_at:'2026-01-01T10:00:00Z'}
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(yes=>{resolve=yes});return {promise,resolve}}
for(const id of ['synthetic-id','ação ?#%','a\\b','a%2Fb','a:b','a+b'])test(`individual URL segment is encoded: ${id}`,async()=>{
 let calls=0
 const api=createAdminApi('https://api.example.test',async config=>{
  calls++;assert.equal(config.url,`/admin/customers/${encodeURIComponent(id)}`)
  assert.equal(config.withCredentials,true);assert.equal(config.method,'get');assert.equal(config.params,undefined)
  assert.equal(config.headers.has('Authorization'),false)
  return {data:{...ITEM,customer_id:id,private:'hidden'},status:200,statusText:'OK',headers:{},config}
 })
 assert.deepEqual(await api.getCustomer(id),{...ITEM,customer_id:id});assert.equal(calls,1)
})
for(const id of ['', '.', '..','a/b','/admin/auth/session','__reserved__','a\u0000b','a\u0085b','\ud800','a'.repeat(1501)])test('invalid document ID never reaches transport',async()=>{
 let calls=0
 const api=createAdminApi('https://api.example.test',async()=>{calls++;throw Error('private')})
 await assert.rejects(api.getCustomer(id),(error:unknown)=>error instanceof AdminApiError&&error.status===400)
 assert.equal(calls,0)
})
for(const status of [400,401,403,404,503])test(`individual HTTP ${status} is sanitized without retries`,async()=>{
 let calls=0
 const api=createAdminApi('https://api.example.test',async config=>{calls++;throw new AxiosError('private','ERR_BAD_RESPONSE',config,undefined,{data:{detail:'private'},status,statusText:'private',headers:{},config})})
 await assert.rejects(api.getCustomer('synthetic'),(error:unknown)=>{
  assert.ok(error instanceof AdminApiError);assert.equal(error.status,status)
  assert.ok(!JSON.stringify(error).includes('private'));assert.equal('config' in error,false);return true
 });assert.equal(calls,1)
})
test('mismatched individual response is rejected',async()=>{
 const api=createAdminApi('https://api.example.test',async config=>({data:ITEM,status:200,statusText:'OK',headers:{},config}))
 await assert.rejects(api.getCustomer('other'),AdminApiError)
})
test('StrictMode load deduplicates; changing ID clears data and ignores old responses',async()=>{
 const old=deferred<typeof ITEM>();let calls=0
 const store=createCustomerDetailStore(()=>{},async id=>{calls++;return id==='old'?old.promise:{...ITEM,customer_id:id}})
 const first=store.load('old');assert.equal(store.load('old'),first)
 assert.equal(store.getSnapshot().status,'loading');assert.equal(store.getSnapshot().customer,null)
 await Promise.resolve();await store.load('new');old.resolve(ITEM);await first
 assert.equal(store.getSnapshot().customer?.customer_id,'new');assert.equal(calls,2)
 store.clear();assert.equal(store.getSnapshot().customer,null)
})
test('loss of session discards in-flight data',async()=>{
 const pending=deferred<typeof ITEM>();const store=createCustomerDetailStore(()=>{},()=>pending.promise)
 const first=store.load('synthetic');await Promise.resolve();store.clear();pending.resolve(ITEM);await first
 assert.equal(store.getSnapshot().status,'idle');assert.equal(store.getSnapshot().customer,null)
})
for(const status of [400,401,403,404,503])test(`detail state correctly distinguishes ${status}`,async()=>{
 let unauthorized=0,calls=0
 const store=createCustomerDetailStore(()=>{unauthorized++},async()=>{calls++;throw new AdminApiError(status===503?'unavailable':'unexpected_response',status)})
 await store.load('synthetic');assert.equal(calls,1);assert.equal(unauthorized,status===401?1:0)
 assert.equal(store.getSnapshot().customer,null)
 assert.equal(store.getSnapshot().status,status===400?'invalid':status===403?'forbidden':status===404?'not_found':'error')
})
test('network failure retries only requested customer manually',async()=>{
 const ids:string[]=[]
 const store=createCustomerDetailStore(()=>{},async id=>{ids.push(id);if(ids.length===1)throw new AdminApiError('network');return ITEM})
 await store.load(ITEM.customer_id);assert.equal(ids.length,1);assert.equal(store.getSnapshot().status,'error')
 await store.retry();assert.deepEqual(ids,[ITEM.customer_id,ITEM.customer_id]);assert.equal(store.getSnapshot().status,'ready')
})

test('unexpected and network errors are sanitized; malformed response cannot display data',async()=>{
 for(const data of [null,{}, {...ITEM,email:null}]){
  const api=createAdminApi('https://api.example.test',async config=>({data,status:200,statusText:'OK',headers:{},config}))
  await assert.rejects(api.getCustomer(ITEM.customer_id),AdminApiError)
 }
 const store=createCustomerDetailStore(()=>{},async()=>{throw Error('synthetic-private-firestore')})
 await store.load('synthetic');assert.equal(store.getSnapshot().customer,null)
 assert.ok(!JSON.stringify(store.getSnapshot()).includes('synthetic-private'))
})
