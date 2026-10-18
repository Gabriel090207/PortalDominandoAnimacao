import {test} from 'node:test'
import assert from 'node:assert/strict'
import {AxiosError} from 'axios'
import {createAdminApi,AdminApiError} from '../src/services/adminApi.ts'
import {createPurchaseConfirmationStore} from '../src/pages/Customers/purchaseConfirmationStore.ts'
const CONFIRMATION={customer_id:'synthetic',approved_purchase_recorded:true,current_payment_validity:'not_verified' as const,requires_kirvano_review:true as const}
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(yes=>{resolve=yes});return {promise,resolve}}
for(const approved of [true,false])test(`credentialed bounded GET projects real contract: ${approved}`,async()=>{
 let calls=0;const id='cliente ação?%'
 const api=createAdminApi('https://api.example.test',async config=>{
  calls++;assert.equal(config.method,'get');assert.equal(config.url,`/admin/customers/${encodeURIComponent(id)}/purchase-confirmation`)
  assert.equal(config.withCredentials,true);assert.equal(config.params,undefined);assert.equal(config.data,undefined)
  assert.equal(config.headers.has('Authorization'),false)
  return {data:{...CONFIRMATION,customer_id:id,approved_purchase_recorded:approved,private:'hidden'},status:200,statusText:'OK',headers:{},config}
 })
 assert.equal(calls,0);assert.deepEqual(await api.getPurchaseConfirmation(id),{...CONFIRMATION,customer_id:id,approved_purchase_recorded:approved});assert.equal(calls,1)
})
for(const id of ['','..','a/b','__reserved__','x\u0000'])test('invalid confirmation ID never reaches transport',async()=>{
 let calls=0;const api=createAdminApi('https://api.example.test',async()=>{calls++;throw Error()})
 await assert.rejects(api.getPurchaseConfirmation(id),AdminApiError);assert.equal(calls,0)
})
for(const data of [null,{}, {...CONFIRMATION,customer_id:'foreign'}, {...CONFIRMATION,approved_purchase_recorded:'false'},
 {...CONFIRMATION,current_payment_validity:'valid'},{...CONFIRMATION,requires_kirvano_review:false}])test('malformed confirmation cannot become approved or negative',async()=>{
 const api=createAdminApi('https://api.example.test',async config=>({data,status:200,statusText:'OK',headers:{},config}))
 await assert.rejects(api.getPurchaseConfirmation('synthetic'),AdminApiError)
})
for(const status of [401,403,404,503])test(`confirmation HTTP ${status} sanitized, no retry`,async()=>{
 let calls=0
 const api=createAdminApi('https://api.example.test',async config=>{calls++;throw new AxiosError('private','ERR_BAD_RESPONSE',config,undefined,
  {data:{detail:'private'},status,statusText:'private',headers:{},config})})
 await assert.rejects(api.getPurchaseConfirmation('synthetic'),(error:unknown)=>{
  assert.ok(error instanceof AdminApiError);assert.equal(error.status,status);assert.ok(!JSON.stringify(error).includes('private'));return true
 });assert.equal(calls,1)
})
test('StrictMode deduplication, changing client and clearing session discard stale replies',async()=>{
 const old=deferred<typeof CONFIRMATION>();let calls=0
 const store=createPurchaseConfirmationStore(()=>{},async id=>{calls++;return id==='old'?old.promise:{...CONFIRMATION,customer_id:id}})
 const first=store.load('old');assert.equal(store.load('old'),first)
 assert.equal(store.getSnapshot().status,'loading');assert.equal(store.getSnapshot().confirmation,null)
 await Promise.resolve();await store.load('new');assert.equal(calls,2)
 old.resolve(CONFIRMATION);await first;assert.equal(store.getSnapshot().confirmation?.customer_id,'new')
 store.clear();assert.equal(store.getSnapshot().confirmation,null)
})
test('late reply cannot restore private data after logout clear',async()=>{
 const pending=deferred<typeof CONFIRMATION>();const store=createPurchaseConfirmationStore(()=>{},()=>pending.promise)
 const first=store.load('synthetic');await Promise.resolve();store.clear();pending.resolve(CONFIRMATION);await first
 assert.equal(store.getSnapshot().status,'idle');assert.equal(store.getSnapshot().confirmation,null)
})
for(const status of [401,403,404,503])test(`store handles ${status} without false negative`,async()=>{
 let unauthorized=0
 const store=createPurchaseConfirmationStore(()=>{unauthorized++},async()=>{throw new AdminApiError(status===503?'unavailable':'unexpected_response',status)})
 await store.load('synthetic');assert.equal(unauthorized,status===401?1:0)
 assert.equal(store.getSnapshot().confirmation,null)
 assert.equal(store.getSnapshot().status,status===403?'forbidden':status===404?'not_found':'error')
})
test('network failure and manual retry affect only confirmation',async()=>{
 const ids:string[]=[]
 const store=createPurchaseConfirmationStore(()=>{},async id=>{ids.push(id);if(ids.length===1)throw new AdminApiError('network');return CONFIRMATION})
 await store.load('synthetic');assert.equal(ids.length,1)
 assert.equal(store.getSnapshot().message,'Não foi possível consultar a confirmação da compra.')
 await store.retry();assert.deepEqual(ids,['synthetic','synthetic']);assert.equal(store.getSnapshot().status,'ready')
})
