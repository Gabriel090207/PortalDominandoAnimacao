import {test} from 'node:test'
import assert from 'node:assert/strict'
import {AxiosError} from 'axios'
import {createAdminApi,AdminApiError} from '../src/services/adminApi.ts'
import {createCustomerSuspensionStore,canSuspendCustomer} from '../src/pages/Customers/customerSuspensionStore.ts'
import type {AdminCustomer} from '../src/services/adminApi.ts'
import type {SessionState} from '../src/session/sessionStore.ts'
const CUSTOMER:AdminCustomer={customer_id:'synthetic',email:'customer@example.test',account_status:'enabled',activation_status:'active',created_at:''}
const SESSION:SessionState={status:'authenticated',loggingOut:false,session:{admin_id:'synthetic-admin',email:'admin@example.test',role:'owner',permissions:['read_customers','suspend_customer']}}
const RESULT={customer_id:'synthetic',activation_status:'suspended' as const,result:'suspended' as const}
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(yes=>{resolve=yes});return {promise,resolve}}
function harness(overrides:Partial<Parameters<typeof createCustomerSuspensionStore>[1]>={}){
 let writes=0,reads=0,unauthorized=0,allowed=true
 const store=createCustomerSuspensionStore('synthetic',{canSuspend:()=>allowed,onUnauthorized:()=>{unauthorized++},
  suspend:async()=>{writes++;return RESULT},refresh:async()=>{reads++},...overrides})
 return {store,counts:()=>({writes,reads,unauthorized}),deny:()=>{allowed=false}}
}

test('suspension is credentialed POST to encoded segment with only explicit confirmation',async()=>{
 let calls=0;const id='cliente ação?%'
 const api=createAdminApi('https://api.example.test',async config=>{
  calls++;assert.equal(config.url,`/admin/customers/${encodeURIComponent(id)}/suspend`)
  assert.equal(config.method,'post');assert.equal(config.withCredentials,true)
  assert.deepEqual(JSON.parse(config.data),{confirm_suspension:true});assert.equal(config.params,undefined)
  assert.equal(config.headers.get('X-Admin-Request'),'1');assert.equal(config.headers.get('Content-Type'),'application/json')
  assert.equal(config.headers.has('Authorization'),false)
  return {data:{...RESULT,customer_id:id,private:'hidden'},status:200,statusText:'OK',headers:{},config}
 })
 assert.equal(calls,0);assert.deepEqual(await api.suspendCustomer(id),{...RESULT,customer_id:id});assert.equal(calls,1)
})
for(const id of ['','..','a/b','__reserved__','x\u0000'])test('unsafe suspension ID never reaches transport',async()=>{
 let calls=0;const api=createAdminApi('https://api.example.test',async()=>{calls++;throw Error()})
 await assert.rejects(api.suspendCustomer(id),AdminApiError);assert.equal(calls,0)
})
for(const data of [null,{}, {...RESULT,customer_id:'foreign'}, {...RESULT,result:'success'}, {...RESULT,activation_status:'active'}])test('unexpected success body is rejected',async()=>{
 const api=createAdminApi('https://api.example.test',async config=>({data,status:200,statusText:'OK',headers:{},config}))
 await assert.rejects(api.suspendCustomer('synthetic'),AdminApiError)
})
for(const status of [400,401,403,404,409,413,415,422,503])test(`POST ${status} sanitized without retry`,async()=>{
 let calls=0
 const api=createAdminApi('https://api.example.test',async config=>{calls++;throw new AxiosError('synthetic-private','ERR_BAD_RESPONSE',config,undefined,
  {data:{detail:'synthetic-private'},status,statusText:'private',headers:{},config})})
 await assert.rejects(api.suspendCustomer('synthetic'),(error:unknown)=>{
  assert.ok(error instanceof AdminApiError);assert.equal(error.status,status);assert.ok(!JSON.stringify(error).includes('synthetic-private'));assert.equal('config' in error,false);return true
 });assert.equal(calls,1)
})
test('opening, unchecked submission and cancellation never write; consent resets each operation',async()=>{
 const {store,counts}=harness();assert.equal(counts().writes,0)
 store.open();assert.equal(store.getSnapshot().consent,false);await store.submit();assert.equal(counts().writes,0)
 store.consent(true);store.cancel();await store.submit();assert.equal(counts().writes,0)
 store.open();assert.equal(store.getSnapshot().consent,false)
})
test('one human confirmation deduplicates writes and refetches only after server confirmation',async()=>{
 const pending=deferred<typeof RESULT>();let writes=0,reads=0
 const {store}=harness({suspend:async()=>{writes++;return pending.promise},refresh:async()=>{reads++}})
 store.open();store.consent(true);const first=store.submit();assert.equal(store.submit(),first)
 assert.equal(store.getSnapshot().status,'submitting');assert.equal(store.getSnapshot().consent,false)
 await Promise.resolve();assert.equal(writes,1);assert.equal(reads,0)
 pending.resolve(RESULT);await first
 assert.equal(reads,1);assert.equal(store.getSnapshot().status,'confirmed');assert.equal(store.getSnapshot().message,'Acesso suspenso com sucesso.')
 await store.submit();assert.equal(writes,1)
})
test('already_suspended has distinct message and reads current state',async()=>{
 const {store,counts}=harness({suspend:async()=>({...RESULT,result:'already_suspended'})})
 store.open();store.consent(true);await store.submit()
 assert.equal(store.getSnapshot().message,'Este cliente já está suspenso.');assert.equal(counts().reads,1)
})
for(const status of [400,401,403,404,409,413,415,422])test(`suspension state treats ${status} as rejection, not success`,async()=>{
 let unauthorized=0
 const {store}=harness({suspend:async()=>{throw new AdminApiError('unexpected_response',status)},onUnauthorized:()=>{unauthorized++}})
 store.open();store.consent(true);await store.submit()
 assert.equal(store.getSnapshot().status,'error');assert.equal(unauthorized,status===401?1:0)
 if(status===409)assert.equal(store.getSnapshot().message,'Não foi possível suspender este cliente nas condições atuais.')
})
for(const kind of ['unavailable','network','unexpected_response'] as const)test(`uncertain ${kind} locks POST until explicit read, no ownership claim`,async()=>{
 let writes=0,reads=0
 const {store}=harness({suspend:async()=>{writes++;throw new AdminApiError(kind,kind==='unavailable'?503:undefined)},refresh:async()=>{reads++}})
 store.open();store.consent(true);await store.submit()
 assert.equal(store.getSnapshot().status,'uncertain');assert.match(store.getSnapshot().message!,/Atualize a situação/)
 store.open();store.consent(true);await store.submit();assert.equal(writes,1);assert.equal(reads,0)
 await store.refresh();assert.equal(reads,1);assert.equal(writes,1);assert.equal(store.getSnapshot().status,'idle')
 assert.ok(!store.getSnapshot().message!.includes('sucesso'));store.open();assert.equal(store.getSnapshot().consent,false)
})
test('failed read after confirmed POST preserves confirmed outcome without fictitious local status',async()=>{
 const {store}=harness({refresh:async()=>{throw new AdminApiError('network')}})
 store.open();store.consent(true);await store.submit();assert.equal(store.getSnapshot().status,'confirmed')
 assert.match(store.getSnapshot().message!,/Não foi possível atualizar a ficha/)
})
test('clearing on customer change/logout ignores late POST and does not start GET',async()=>{
 const pending=deferred<typeof RESULT>();let reads=0
 const {store}=harness({suspend:()=>pending.promise,refresh:async()=>{reads++}})
 store.open();store.consent(true);const first=store.submit();await Promise.resolve();store.clear()
 pending.resolve(RESULT);await first
 assert.equal(store.getSnapshot().status,'idle');assert.equal(store.getSnapshot().consent,false);assert.equal(reads,0)
})
test('logout before dispatch prevents POST; revoked visual permission also blocks submission',async()=>{
 const h=harness();h.store.open();h.store.consent(true);h.deny();await h.store.submit();assert.equal(h.counts().writes,0)
 const other=harness();other.store.open();other.store.consent(true);const pending=other.store.submit();other.store.clear();await pending;assert.equal(other.counts().writes,0)
})
test('late refresh cannot restore state cleared by session invalidation',async()=>{
 const read=deferred<void>();const {store}=harness({refresh:()=>read.promise})
 store.open();store.consent(true);const pending=store.submit();await Promise.resolve();await Promise.resolve();await Promise.resolve()
 store.clear();read.resolve();await pending;assert.equal(store.getSnapshot().status,'idle')
})

for(const active of [true,false])test(`uncertain POST followed by explicit GET reflects backend status: ${active}`,async()=>{
 const methods:string[]=[];let customer={...CUSTOMER}
 const api=createAdminApi('https://api.example.test',async config=>{
  methods.push(config.method!)
  if(config.method==='post')throw new AxiosError('timeout','ECONNABORTED',config)
  assert.equal(config.url,'/admin/customers/synthetic')
  return {data:{...CUSTOMER,activation_status:active?'suspended':'active'},status:200,statusText:'OK',headers:{},config}
 })
 const store=createCustomerSuspensionStore('synthetic',{canSuspend:()=>canSuspendCustomer(customer,SESSION),
  onUnauthorized:()=>{},suspend:api.suspendCustomer,refresh:async()=>{customer=await api.getCustomer('synthetic')}})
 store.open();store.consent(true);await store.submit();assert.deepEqual(methods,['post'])
 assert.equal(customer.activation_status,'active');await store.refresh();assert.deepEqual(methods,['post','get'])
 assert.equal(customer.activation_status,active?'suspended':'active');assert.ok(!store.getSnapshot().message!.includes('sucesso'))
 store.open();assert.equal(store.getSnapshot().status,active?'idle':'confirming');assert.equal(store.getSnapshot().consent,false)
})

for(const role of ['owner','operator'] as const)test(`suspension eligibility for ${role} uses permissions, not purchase approval`,()=>{
 assert.ok(SESSION.status==='authenticated')
 const session={...SESSION,session:{...SESSION.session,role}}
 assert.equal(canSuspendCustomer(CUSTOMER,session),true)
 for(const permissions of [[],['read_customers'],['suspend_customer']])assert.equal(canSuspendCustomer(CUSTOMER,{...session,session:{...session.session,permissions:permissions as typeof session.session.permissions}}),false)
 for(const customer of [null,{...CUSTOMER,activation_status:'pending' as const},{...CUSTOMER,activation_status:'suspended' as const},{...CUSTOMER,account_status:'blocked' as const}])assert.equal(canSuspendCustomer(customer,session),false)
 for(const status of ['checking','unauthenticated','error'] as const)assert.equal(canSuspendCustomer(CUSTOMER,{status}),false)
 assert.equal(canSuspendCustomer(CUSTOMER,{...session,loggingOut:true}),false)
})

for(const code of ['ECONNABORTED','ERR_NETWORK'])test(`${code} is sanitized and never retries suspension transport`,async()=>{
 let calls=0
 const api=createAdminApi('https://api.example.test',async config=>{
  calls++;throw new AxiosError('synthetic-sensitive-detail',code,config)
 })
 await assert.rejects(api.suspendCustomer('synthetic'),(error:unknown)=>{
  assert.ok(error instanceof AdminApiError);assert.equal(error.kind,'network');assert.equal(error.status,undefined)
  assert.ok(!JSON.stringify(error).includes('synthetic-sensitive-detail'));assert.equal('config' in error,false);return true
 })
 assert.equal(calls,1)
})
