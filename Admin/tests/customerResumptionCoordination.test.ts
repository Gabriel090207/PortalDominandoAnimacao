import {test} from 'node:test'
import assert from 'node:assert/strict'
import {AxiosError} from 'axios'
import {AdminApiError,createAdminApi} from '../src/services/adminApi.ts'
import type {AdminCustomer} from '../src/services/adminApi.ts'
import {createCustomerOperationCoordinator} from '../src/pages/Customers/customerOperationCoordinator.ts'
import {createCustomerActivationStore} from '../src/pages/Customers/customerActivationStore.ts'
import {createCustomerSuspensionStore,canSuspendCustomer} from '../src/pages/Customers/customerSuspensionStore.ts'
import {createCustomerResumptionStore,canResumeCustomer} from '../src/pages/Customers/customerResumptionStore.ts'
import {createCustomerDetailStore} from '../src/pages/Customers/customerDetailStore.ts'
import {createPurchaseConfirmationStore} from '../src/pages/Customers/purchaseConfirmationStore.ts'
import {createSessionStore} from '../src/session/sessionStore.ts'
const CUSTOMER:AdminCustomer={customer_id:'synthetic',email:'customer@example.test',account_status:'enabled',activation_status:'suspended',created_at:''}
const RESULT={customer_id:'synthetic',activation_status:'active' as const,result:'resumed' as const}
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(yes=>{resolve=yes});return {promise,resolve}}

for(const pair of [['resume','activate'],['activate','resume'],['suspend','resume'],['resume','suspend']] as const)test(`${pair.join('/')} cannot confirm or write concurrently`,async()=>{
 const coordinator=createCustomerOperationCoordinator();let writes=0
 const waiting=deferred<void>()
 const common={coordinator,onUnauthorized:()=>{},refresh:async()=>{}}
 const actions={
  resume:createCustomerResumptionStore('synthetic',{...common,canResume:()=>true,resume:async()=>{writes++;await waiting.promise;return RESULT}}),
  suspend:createCustomerSuspensionStore('synthetic',{...common,canSuspend:()=>true,suspend:async()=>{writes++;await waiting.promise;return {customer_id:'synthetic',activation_status:'suspended',result:'suspended'}}}),
  activate:createCustomerActivationStore('synthetic',{...common,canActivate:()=>true,activate:async()=>{writes++;await waiting.promise;return {customer_id:'synthetic',activation_status:'active',result:'activated'}}}),
 }
 const one=actions[pair[0]],two=actions[pair[1]]
 one.open();two.open();assert.equal(one.getSnapshot().status,'confirming');assert.equal(two.getSnapshot().status,'idle')
 one.consent(true);const pending=one.submit();await Promise.resolve()
 two.open();two.consent(true);await two.submit();assert.equal(writes,1)
 waiting.resolve();await pending
 two.open();assert.equal(two.getSnapshot().status,'confirming');assert.equal(two.getSnapshot().consent,false)
 two.cancel();assert.equal(coordinator.getSnapshot(),undefined)
})

test('confirmed resume/suspend/resume cycles require fresh consent and GET without changing purchase facts',async()=>{
 let server={...CUSTOMER};const methods:string[]=[]
 const api=createAdminApi('https://api.example.test',async config=>{
  methods.push(config.method!+' '+config.url)
  let data:unknown
  if(config.method==='post'){
   const resume=config.url?.endsWith('/resume')
   assert.deepEqual(JSON.parse(config.data),resume?{confirm_resumption:true}:{confirm_suspension:true})
   server={...server,activation_status:resume?'active':'suspended'}
   data={customer_id:'synthetic',activation_status:server.activation_status,result:resume?'resumed':'suspended'}
  }else if(config.url?.endsWith('/purchase-confirmation')){
   data={customer_id:'synthetic',approved_purchase_recorded:false,current_payment_validity:'not_verified',requires_kirvano_review:true}
  }else data=server
  return {data,status:200,statusText:'OK',headers:{},config}
 })
 const session={status:'authenticated' as const,loggingOut:false,session:{admin_id:'synthetic-admin',email:'admin@example.test',role:'operator' as const,permissions:['read_customers','resume_customer','suspend_customer'] as ('read_customers'|'resume_customer'|'suspend_customer')[]}}
 const detail=createCustomerDetailStore(()=>{},api.getCustomer),purchase=createPurchaseConfirmationStore(()=>{},api.getPurchaseConfirmation)
 await detail.load('synthetic');await purchase.load('synthetic');const previous=purchase.getSnapshot()
 const coordinator=createCustomerOperationCoordinator()
 const refresh=async()=>{await detail.load('synthetic',true);if(detail.getSnapshot().status!=='ready')throw new AdminApiError('unavailable')}
 const resumption=createCustomerResumptionStore('synthetic',{coordinator,onUnauthorized:()=>{},canResume:()=>detail.getSnapshot().status==='ready'&&canResumeCustomer(detail.getSnapshot().customer,session),resume:api.resumeCustomer,refresh})
 const suspension=createCustomerSuspensionStore('synthetic',{coordinator,onUnauthorized:()=>{},canSuspend:()=>detail.getSnapshot().status==='ready'&&canSuspendCustomer(detail.getSnapshot().customer,session),suspend:api.suspendCustomer,refresh})
 for(const action of [resumption,suspension,resumption]){
  assert.equal(action.canOpen(),true);action.open();assert.equal(action.getSnapshot().consent,false)
  const count=methods.length;await action.submit();assert.equal(methods.length,count)
  action.consent(true);await action.submit();assert.equal(action.getSnapshot().status,'confirmed')
  assert.equal(action.canOpen(),false);assert.equal(purchase.getSnapshot(),previous)
  assert.equal(detail.getSnapshot().customer?.account_status,'enabled')
 }
 assert.deepEqual(methods,['get /admin/customers/synthetic','get /admin/customers/synthetic/purchase-confirmation',
  'post /admin/customers/synthetic/resume','get /admin/customers/synthetic',
  'post /admin/customers/synthetic/suspend','get /admin/customers/synthetic',
  'post /admin/customers/synthetic/resume','get /admin/customers/synthetic'])
 assert.deepEqual(detail.getSnapshot().customer,{...CUSTOMER,activation_status:'active'})
})


test('legacy-like 409 cannot switch to activation, fake audit or fictitious active state',async()=>{
 const methods:string[]=[]
 const api=createAdminApi('https://api.example.test',async config=>{
  methods.push(config.method!+' '+config.url)
  if(config.method==='post')throw new AxiosError('synthetic-private','ERR_BAD_RESPONSE',config,undefined,{data:{detail:'synthetic-private missing audit'},status:409,statusText:'Conflict',headers:{},config})
  return {data:CUSTOMER,status:200,statusText:'OK',headers:{},config}
 })
 let customer={...CUSTOMER}
 const store=createCustomerResumptionStore('synthetic',{canResume:()=>true,onUnauthorized:()=>{},resume:api.resumeCustomer,refresh:async()=>{customer=await api.getCustomer('synthetic')}})
 store.open();store.consent(true);await store.submit()
 assert.equal(store.getSnapshot().status,'error');assert.match(store.getSnapshot().message!,/condições atuais.*Verifique a situação/)
 assert.ok(!/auditoria|audit|legado|synthetic-private|sucesso/.test(store.getSnapshot().message!))
 store.open();store.consent(true);await store.submit();assert.equal(methods.length,1)
 await store.refresh();assert.equal(customer.activation_status,'suspended');assert.equal(store.getSnapshot().status,'idle')
 assert.deepEqual(methods,['post /admin/customers/synthetic/resume','get /admin/customers/synthetic'])
 store.open();assert.equal(store.getSnapshot().consent,false)
})


test('uncertain resume locks activation and suspension until successful explicit read',async()=>{
 const coordinator=createCustomerOperationCoordinator();let failRead=true,reads=0,writes=0
 const common={coordinator,onUnauthorized:()=>{},refresh:async()=>{}}
 const activation=createCustomerActivationStore('synthetic',{...common,canActivate:()=>true})
 const suspension=createCustomerSuspensionStore('synthetic',{...common,canSuspend:()=>true})
 const resumption=createCustomerResumptionStore('synthetic',{...common,canResume:()=>true,
  resume:async()=>{writes++;throw new AdminApiError('unavailable',503)},refresh:async()=>{reads++;if(failRead)throw new AdminApiError('network')}})
 resumption.open();resumption.consent(true);await resumption.submit()
 for(const action of [activation,suspension]){action.open();assert.equal(action.getSnapshot().status,'idle')}
 await resumption.refresh();assert.equal(resumption.getSnapshot().status,'uncertain')
 for(const action of [activation,suspension]){action.open();assert.equal(action.getSnapshot().status,'idle')}
 failRead=false;await resumption.refresh();assert.equal(reads,2);assert.equal(writes,1)
 assert.ok(!resumption.getSnapshot().message!.includes('sucesso'))
 suspension.open();assert.equal(suspension.getSnapshot().status,'confirming')
})


test('confirmed POST with failed read cannot reopen until reconciliation succeeds',async()=>{
 let failRead=true,reads=0,writes=0
 const detail=createCustomerDetailStore(()=>{},async()=>{if(failRead)throw new AdminApiError('network');return CUSTOMER})
 const store=createCustomerResumptionStore('synthetic',{canResume:()=>true,onUnauthorized:()=>{},
  resume:async()=>{writes++;return RESULT},refresh:async()=>{reads++;await detail.load('synthetic',true);if(detail.getSnapshot().status!=='ready')throw new AdminApiError('unavailable')}})
 store.open();store.consent(true);await store.submit()
 assert.equal(store.getSnapshot().status,'confirmed');assert.equal(store.canOpen(),false);assert.equal(detail.getSnapshot().customer,null)
 assert.match(store.getSnapshot().message!,/sucesso.*Não foi possível atualizar a ficha/)
 store.open();store.consent(true);await store.submit();assert.equal(writes,1)
 failRead=false;await store.refresh();assert.equal(reads,2);assert.equal(store.canOpen(),true)
 store.open();assert.equal(store.getSnapshot().consent,false)
})

for(const reason of ['logout','unauthorized'] as const)test(`${reason} discards pending resumption and private data`,async()=>{
 const reply=deferred<typeof RESULT>();let reads=0
 const session=createSessionStore({login:async()=>({admin_id:'synthetic'}),getSession:async()=>({admin_id:'synthetic',email:'admin@example.test',role:'owner',permissions:['read_customers','resume_customer']}),logout:async()=>({success:true})})
 await session.verify()
 const detail=createCustomerDetailStore(session.handleUnauthorized,async()=>CUSTOMER)
 const purchase=createPurchaseConfirmationStore(session.handleUnauthorized,async()=>({customer_id:'synthetic',approved_purchase_recorded:true,current_payment_validity:'not_verified',requires_kirvano_review:true}))
 await detail.load('synthetic');await purchase.load('synthetic')
 const resumption=createCustomerResumptionStore('synthetic',{canResume:()=>session.getSnapshot().status==='authenticated',onUnauthorized:session.handleUnauthorized,resume:()=>reply.promise,refresh:async()=>{reads++}})
 const unsubscribe=session.subscribe(()=>{const current=session.getSnapshot();if(current.status!=='authenticated'||current.loggingOut){detail.clear();purchase.clear();resumption.clear()}})
 resumption.open();resumption.consent(true);const pending=resumption.submit();await Promise.resolve()
 if(reason==='logout')await session.logout();else session.handleUnauthorized(new AdminApiError('invalid_session',401))
 reply.resolve(RESULT);await pending
 assert.equal(detail.getSnapshot().customer,null);assert.equal(purchase.getSnapshot().confirmation,null)
 assert.deepEqual(resumption.getSnapshot(),{status:'idle',consent:false});assert.equal(reads,0);unsubscribe()
})
