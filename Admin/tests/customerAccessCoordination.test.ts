import {test} from 'node:test'
import assert from 'node:assert/strict'
import {AdminApiError,createAdminApi} from '../src/services/adminApi.ts'
import {createCustomerOperationCoordinator} from '../src/pages/Customers/customerOperationCoordinator.ts'
import {createCustomerActivationStore} from '../src/pages/Customers/customerActivationStore.ts'
import {createCustomerSuspensionStore} from '../src/pages/Customers/customerSuspensionStore.ts'
import {createCustomerDetailStore} from '../src/pages/Customers/customerDetailStore.ts'
import {createPurchaseConfirmationStore} from '../src/pages/Customers/purchaseConfirmationStore.ts'
import {createSessionStore} from '../src/session/sessionStore.ts'
const CUSTOMER={customer_id:'synthetic',email:'customer@example.test',account_status:'enabled' as const,activation_status:'active' as const,created_at:''}
const RESULT={customer_id:'synthetic',activation_status:'suspended' as const,result:'suspended' as const}
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(yes=>{resolve=yes});return {promise,resolve}}

for(const first of ['activation','suspension'])test(`local coordinator excludes incompatible ${first} confirmation and writes`,async()=>{
 const coordinator=createCustomerOperationCoordinator();const waiting=deferred<void>();let activated=0,suspended=0
 const activation=createCustomerActivationStore('synthetic',{coordinator,canActivate:()=>true,onUnauthorized:()=>{},refresh:async()=>{},activate:async()=>{activated++;await waiting.promise;return {customer_id:'synthetic',activation_status:'active',result:'activated'}}})
 const suspension=createCustomerSuspensionStore('synthetic',{coordinator,canSuspend:()=>true,onUnauthorized:()=>{},refresh:async()=>{},suspend:async()=>{suspended++;await waiting.promise;return RESULT}})
 const [one,two]=first==='activation'?[activation,suspension]:[suspension,activation]
 one.open();two.open();assert.equal(one.getSnapshot().status,'confirming');assert.equal(two.getSnapshot().status,'idle')
 one.cancel();two.open();assert.equal(two.getSnapshot().status,'confirming');two.cancel()
 one.open();one.consent(true);const pending=one.submit();await Promise.resolve()
 two.open();two.consent(true);await two.submit()
 assert.equal(activated+suspended,1);assert.notEqual(coordinator.getSnapshot(),undefined)
 waiting.resolve();await pending;assert.equal(coordinator.getSnapshot(),undefined)
 two.open();assert.equal(two.getSnapshot().status,'confirming');assert.equal(two.getSnapshot().consent,false)
})

test('uncertain write keeps other operations locked until successful explicit GET',async()=>{
 const coordinator=createCustomerOperationCoordinator();let reads=0,failRead=true
 const activation=createCustomerActivationStore('synthetic',{coordinator,canActivate:()=>true,onUnauthorized:()=>{},refresh:async()=>{}})
 const suspension=createCustomerSuspensionStore('synthetic',{coordinator,canSuspend:()=>true,onUnauthorized:()=>{},
  suspend:async()=>{throw new AdminApiError('unavailable',503)},refresh:async()=>{reads++;if(failRead)throw new AdminApiError('network')}})
 suspension.open();suspension.consent(true);await suspension.submit()
 activation.open();assert.equal(activation.getSnapshot().status,'idle')
 await suspension.refresh();activation.open();assert.equal(activation.getSnapshot().status,'idle');assert.equal(reads,1)
 failRead=false;await suspension.refresh();activation.open();assert.equal(activation.getSnapshot().status,'confirming')
 assert.equal(reads,2);assert.ok(!suspension.getSnapshot().message!.includes('sucesso'))
})

test('confirmed POST refetches cadastral facts and preserves purchase confirmation',async()=>{
 const methods:string[]=[]
 const api=createAdminApi('https://api.example.test',async config=>{
  methods.push(config.method!+' '+config.url)
  const data=config.url?.endsWith('/suspend')?RESULT:config.url?.endsWith('/purchase-confirmation')?
   {customer_id:'synthetic',approved_purchase_recorded:false,current_payment_validity:'not_verified',requires_kirvano_review:true}:
   {...CUSTOMER,activation_status:methods.some(method=>method.startsWith('post'))?'suspended':'active'}
  return {data,status:200,statusText:'OK',headers:{},config}
 })
 const detail=createCustomerDetailStore(()=>{},api.getCustomer)
 const purchase=createPurchaseConfirmationStore(()=>{},api.getPurchaseConfirmation)
 await detail.load('synthetic');await purchase.load('synthetic');const previous=purchase.getSnapshot()
 const suspension=createCustomerSuspensionStore('synthetic',{canSuspend:()=>detail.getSnapshot().status==='ready',onUnauthorized:()=>{},
  suspend:api.suspendCustomer,refresh:async()=>{await detail.load('synthetic',true);if(detail.getSnapshot().status!=='ready')throw new AdminApiError('unavailable')}})
 suspension.open();suspension.consent(true);await suspension.submit()
 assert.deepEqual(methods,['get /admin/customers/synthetic','get /admin/customers/synthetic/purchase-confirmation','post /admin/customers/synthetic/suspend','get /admin/customers/synthetic'])
 assert.deepEqual(detail.getSnapshot().customer,{...CUSTOMER,activation_status:'suspended'})
 assert.equal(purchase.getSnapshot(),previous);assert.equal(suspension.getSnapshot().status,'confirmed')
})

test('failed GET after confirmed POST removes stale customer and keeps other actions locked',async()=>{
 let fail=false
 const detail=createCustomerDetailStore(()=>{},async()=>{if(fail)throw new AdminApiError('network');return CUSTOMER})
 await detail.load('synthetic');const coordinator=createCustomerOperationCoordinator()
 const suspension=createCustomerSuspensionStore('synthetic',{coordinator,canSuspend:()=>detail.getSnapshot().status==='ready',onUnauthorized:()=>{},suspend:async()=>RESULT,
  refresh:async()=>{await detail.load('synthetic',true);if(detail.getSnapshot().status!=='ready')throw new AdminApiError('unavailable')}})
 fail=true;suspension.open();suspension.consent(true);await suspension.submit()
 assert.equal(detail.getSnapshot().customer,null);assert.equal(detail.getSnapshot().status,'error')
 assert.match(suspension.getSnapshot().message!,/sucesso.*Não foi possível atualizar a ficha/)
 assert.notEqual(coordinator.getSnapshot(),undefined)
 fail=false;await suspension.refresh();assert.equal(detail.getSnapshot().status,'ready');assert.equal(coordinator.getSnapshot(),undefined)
})

for(const reason of ['logout','unauthorized'] as const)test(`${reason} invalidates private stores and late POST replies`,async()=>{
 const reply=deferred<typeof RESULT>();let reads=0
 const session=createSessionStore({login:async()=>({admin_id:'synthetic'}),getSession:async()=>({admin_id:'synthetic',email:'admin@example.test',role:'owner',permissions:['read_customers','suspend_customer']}),logout:async()=>({success:true})})
 await session.verify()
 const detail=createCustomerDetailStore(session.handleUnauthorized,async()=>CUSTOMER)
 const purchase=createPurchaseConfirmationStore(session.handleUnauthorized,async()=>({customer_id:'synthetic',approved_purchase_recorded:true,current_payment_validity:'not_verified',requires_kirvano_review:true}))
 await detail.load('synthetic');await purchase.load('synthetic')
 const suspension=createCustomerSuspensionStore('synthetic',{canSuspend:()=>session.getSnapshot().status==='authenticated',onUnauthorized:session.handleUnauthorized,suspend:()=>reply.promise,refresh:async()=>{reads++}})
 const unsubscribe=session.subscribe(()=>{const current=session.getSnapshot();if(current.status!=='authenticated'||current.loggingOut){detail.clear();purchase.clear();suspension.clear()}})
 suspension.open();suspension.consent(true);const pending=suspension.submit();await Promise.resolve()
 if(reason==='logout')await session.logout();else session.handleUnauthorized(new AdminApiError('invalid_session',401))
 reply.resolve(RESULT);await pending
 assert.equal(detail.getSnapshot().customer,null);assert.equal(purchase.getSnapshot().confirmation,null)
 assert.deepEqual(suspension.getSnapshot(),{status:'idle',consent:false});assert.equal(reads,0);unsubscribe()
})

test('a completed action cannot start a competing read-back during another operation',async()=>{
 const coordinator=createCustomerOperationCoordinator();let reads=0
 const activation=createCustomerActivationStore('synthetic',{coordinator,canActivate:()=>true,onUnauthorized:()=>{},refresh:async()=>{reads++},activate:async()=>({customer_id:'synthetic',activation_status:'active',result:'activated'})})
 const suspension=createCustomerSuspensionStore('synthetic',{coordinator,canSuspend:()=>true,onUnauthorized:()=>{},refresh:async()=>{},suspend:async()=>RESULT})
 activation.open();activation.consent(true);await activation.submit();assert.equal(reads,1)
 suspension.open();await activation.refresh();assert.equal(reads,1)
 suspension.cancel();await activation.refresh();assert.equal(reads,2)
})
