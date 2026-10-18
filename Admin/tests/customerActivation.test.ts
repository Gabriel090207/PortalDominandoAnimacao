import {test} from 'node:test'
import assert from 'node:assert/strict'
import {AxiosError} from 'axios'
import {createAdminApi,AdminApiError} from '../src/services/adminApi.ts'
import {createCustomerActivationStore,canActivateCustomer} from '../src/pages/Customers/customerActivationStore.ts'
import type {AdminCustomer,AdminPurchaseConfirmation} from '../src/services/adminApi.ts'
import type {SessionState} from '../src/session/sessionStore.ts'
const CUSTOMER:AdminCustomer={customer_id:'synthetic',email:'customer@example.test',account_status:'enabled',activation_status:'pending',created_at:''}
const PURCHASE:AdminPurchaseConfirmation={customer_id:'synthetic',approved_purchase_recorded:true,current_payment_validity:'not_verified',requires_kirvano_review:true}
const SESSION:SessionState={status:'authenticated',loggingOut:false,session:{admin_id:'synthetic-admin',email:'admin@example.test',role:'owner',permissions:['read_customers','activate_customer']}}
const RESULT={customer_id:'synthetic',activation_status:'active' as const,result:'activated' as const}
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(yes=>{resolve=yes});return {promise,resolve}}
function harness(overrides:Partial<Parameters<typeof createCustomerActivationStore>[1]>={}){
 let writes=0,reads=0,unauthorized=0,allowed=true
 const store=createCustomerActivationStore('synthetic',{canActivate:()=>allowed,onUnauthorized:()=>{unauthorized++},
  activate:async()=>{writes++;return RESULT},refresh:async()=>{reads++},...overrides})
 return {store,counts:()=>({writes,reads,unauthorized}),deny:()=>{allowed=false}}
}

test('activation is credentialed POST to encoded segment with only explicit confirmation',async()=>{
 let calls=0;const id='cliente ação?%'
 const api=createAdminApi('https://api.example.test',async config=>{
  calls++;assert.equal(config.url,`/admin/customers/${encodeURIComponent(id)}/activate`)
  assert.equal(config.method,'post');assert.equal(config.withCredentials,true)
  assert.deepEqual(JSON.parse(config.data),{confirm_activation:true});assert.equal(config.params,undefined)
  assert.equal(config.headers.get('X-Admin-Request'),'1');assert.equal(config.headers.get('Content-Type'),'application/json')
  assert.equal(config.headers.has('Authorization'),false)
  return {data:{...RESULT,customer_id:id,private:'hidden'},status:200,statusText:'OK',headers:{},config}
 })
 assert.equal(calls,0);assert.deepEqual(await api.activateCustomer(id),{...RESULT,customer_id:id});assert.equal(calls,1)
})
for(const id of ['','..','a/b','__reserved__','x\u0000'])test('unsafe activation ID never reaches transport',async()=>{
 let calls=0;const api=createAdminApi('https://api.example.test',async()=>{calls++;throw Error()})
 await assert.rejects(api.activateCustomer(id),AdminApiError);assert.equal(calls,0)
})
for(const data of [null,{}, {...RESULT,customer_id:'foreign'}, {...RESULT,result:'success'}, {...RESULT,activation_status:'pending'}])test('unexpected success body is rejected',async()=>{
 const api=createAdminApi('https://api.example.test',async config=>({data,status:200,statusText:'OK',headers:{},config}))
 await assert.rejects(api.activateCustomer('synthetic'),AdminApiError)
})
for(const status of [400,401,403,404,409,413,415,422,503])test(`POST ${status} sanitized without retry`,async()=>{
 let calls=0
 const api=createAdminApi('https://api.example.test',async config=>{calls++;throw new AxiosError('synthetic-private','ERR_BAD_RESPONSE',config,undefined,
  {data:{detail:'synthetic-private'},status,statusText:'private',headers:{},config})})
 await assert.rejects(api.activateCustomer('synthetic'),(error:unknown)=>{
  assert.ok(error instanceof AdminApiError);assert.equal(error.status,status);assert.ok(!JSON.stringify(error).includes('synthetic-private'));assert.equal('config' in error,false);return true
 });assert.equal(calls,1)
})
for(const role of ['owner','operator'] as const)test(`visual eligibility uses permissions for ${role}`,()=>{
 assert.ok(SESSION.status==='authenticated')
 const session={...SESSION,session:{...SESSION.session,role}}
 assert.equal(canActivateCustomer(CUSTOMER,PURCHASE,session),true)
 for(const permissions of [[],['read_customers'],['activate_customer']])assert.equal(canActivateCustomer(CUSTOMER,PURCHASE,{...session,session:{...session.session,permissions:permissions as typeof session.session.permissions}}),false)
})
test('incompatible state, missing data, session or approval never enables action',()=>{
 for(const customer of [null,{...CUSTOMER,activation_status:'active' as const},{...CUSTOMER,activation_status:'suspended' as const},{...CUSTOMER,account_status:'blocked' as const}])assert.equal(canActivateCustomer(customer,PURCHASE,SESSION),false)
 for(const purchase of [null,{...PURCHASE,approved_purchase_recorded:false},{...PURCHASE,customer_id:'foreign'}])assert.equal(canActivateCustomer(CUSTOMER,purchase,SESSION),false)
 for(const status of ['checking','unauthenticated','error'] as const)assert.equal(canActivateCustomer(CUSTOMER,PURCHASE,{status}),false)
 assert.equal(canActivateCustomer(CUSTOMER,PURCHASE,{...SESSION,loggingOut:true} as SessionState),false)
})
test('opening, unchecked submission and cancellation never write; consent resets each operation',async()=>{
 const {store,counts}=harness();assert.equal(counts().writes,0)
 store.open();assert.equal(store.getSnapshot().consent,false);await store.submit();assert.equal(counts().writes,0)
 store.consent(true);store.cancel();await store.submit();assert.equal(counts().writes,0)
 store.open();assert.equal(store.getSnapshot().consent,false)
})
test('one human confirmation deduplicates writes and refetches only after server confirmation',async()=>{
 const pending=deferred<typeof RESULT>();let writes=0,reads=0
 const {store}=harness({activate:async()=>{writes++;return pending.promise},refresh:async()=>{reads++}})
 store.open();store.consent(true);const first=store.submit();assert.equal(store.submit(),first)
 assert.equal(store.getSnapshot().status,'submitting');assert.equal(store.getSnapshot().consent,false)
 await Promise.resolve();assert.equal(writes,1);assert.equal(reads,0)
 pending.resolve(RESULT);await first
 assert.equal(reads,1);assert.equal(store.getSnapshot().status,'confirmed');assert.equal(store.getSnapshot().message,'Acesso ativado com sucesso.')
 await store.submit();assert.equal(writes,1)
})
test('already_active has distinct message and reads current state',async()=>{
 const {store,counts}=harness({activate:async()=>({...RESULT,result:'already_active'})})
 store.open();store.consent(true);await store.submit()
 assert.equal(store.getSnapshot().message,'Este cliente já está ativo.');assert.equal(counts().reads,1)
})
for(const status of [400,401,403,404,409,413,415,422])test(`activation state treats ${status} as rejection, not success`,async()=>{
 let unauthorized=0
 const {store}=harness({activate:async()=>{throw new AdminApiError('unexpected_response',status)},onUnauthorized:()=>{unauthorized++}})
 store.open();store.consent(true);await store.submit()
 assert.equal(store.getSnapshot().status,'error');assert.equal(unauthorized,status===401?1:0)
 if(status===409)assert.equal(store.getSnapshot().message,'Não foi possível ativar este cliente nas condições atuais.')
})
for(const kind of ['unavailable','network','unexpected_response'] as const)test(`uncertain ${kind} locks POST until explicit read, no ownership claim`,async()=>{
 let writes=0,reads=0
 const {store}=harness({activate:async()=>{writes++;throw new AdminApiError(kind,kind==='unavailable'?503:undefined)},refresh:async()=>{reads++}})
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
 const {store}=harness({activate:()=>pending.promise,refresh:async()=>{reads++}})
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
  return {data:{...CUSTOMER,activation_status:active?'active':'pending'},status:200,statusText:'OK',headers:{},config}
 })
 const store=createCustomerActivationStore('synthetic',{canActivate:()=>canActivateCustomer(customer,PURCHASE,SESSION),
  onUnauthorized:()=>{},activate:api.activateCustomer,refresh:async()=>{customer=await api.getCustomer('synthetic')}})
 store.open();store.consent(true);await store.submit();assert.deepEqual(methods,['post'])
 assert.equal(customer.activation_status,'pending');await store.refresh();assert.deepEqual(methods,['post','get'])
 assert.equal(customer.activation_status,active?'active':'pending');assert.ok(!store.getSnapshot().message!.includes('sucesso'))
 store.open();assert.equal(store.getSnapshot().status,active?'idle':'confirming');assert.equal(store.getSnapshot().consent,false)
})
