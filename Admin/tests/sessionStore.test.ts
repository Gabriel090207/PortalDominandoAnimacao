import {test} from 'node:test'
import assert from 'node:assert/strict'
import {createSessionStore} from '../src/session/sessionStore.ts'
import {AdminApiError} from '../src/services/adminApi.ts'
import type {AdminSession} from '../src/services/adminApi.ts'
import type {SessionServices} from '../src/session/sessionStore.ts'
const SESSION: AdminSession = {admin_id:'synthetic',email:'admin@example.test',role:'operator',permissions:['read_customers']}
function services(changes: Partial<SessionServices> = {}):SessionServices {
  return {async login(){return {admin_id:'synthetic'}},async getSession(){return SESSION},async logout(){return {success:true}},...changes}
}
function deferred<T>() { let resolve!: (value:T)=>void; let reject!: (error:unknown)=>void; const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject} }

test('initial verification blocks access; StrictMode duplicate effect shares one call',async()=>{
  let calls=0
  const pending=deferred<AdminSession>()
  const store=createSessionStore(services({getSession(){calls++;return pending.promise}}))
  assert.equal(store.getSnapshot().status,'checking')
  const first=store.verify(),second=store.verify()
  assert.equal(first,second)
  await Promise.resolve()
  assert.equal(calls,1)
  pending.resolve(SESSION)
  await first
  assert.deepEqual(store.getSnapshot(),{status:'authenticated',session:SESSION,loggingOut:false})
})

for(const error of [new AdminApiError('invalid_session',401),new AdminApiError('unavailable',503),new AdminApiError('network')]){
 test(`verification ${error.kind} never authorizes`,async()=>{
  const store=createSessionStore(services({async getSession(){throw error}}))
  await store.verify()
  const state=store.getSnapshot()
  assert.equal(state.status,error.status===401?'unauthenticated':'error')
  assert.ok(!('session' in state))
  if(state.status==='error')assert.match(state.message!,/não significa/i)
 })
}

test('retry works even for synchronous configuration errors',async()=>{
 let calls=0
 const store=createSessionStore(services({getSession(){if(++calls===1)throw new AdminApiError('configuration');return Promise.resolve(SESSION)}}))
 await store.verify();assert.equal(store.getSnapshot().status,'error')
 await store.verify();assert.equal(store.getSnapshot().status,'authenticated');assert.equal(calls,2)
})

test('login id alone does not authorize; explicit confirmation required',async()=>{
 let logins=0,reads=0
 const store=createSessionStore(services({async login(){logins++;return {admin_id:'synthetic'}},async getSession(){reads++;return SESSION}}))
 await store.login({email:'invalid',password:'synthetic-password'})
 assert.notEqual(store.getSnapshot().status,'authenticated')
 await store.confirmLogin()
 assert.equal(store.getSnapshot().status,'authenticated');assert.equal(logins,1);assert.equal(reads,1)
 assert.ok(!JSON.stringify(store.getSnapshot()).includes('synthetic-password'))
})

test('failed confirmation blocks panel, retry checks session only',async()=>{
 let logins=0,reads=0
 const store=createSessionStore(services({async login(){logins++;return {admin_id:'synthetic'}},async getSession(){if(++reads===1)throw new AdminApiError('network');return SESSION}}))
 await store.login({email:'x',password:'synthetic'})
 await assert.rejects(store.confirmLogin())
 assert.equal(store.getSnapshot().status,'error')
 await store.verify()
 assert.equal(store.getSnapshot().status,'authenticated');assert.equal(logins,1)
})

test('new application/reload must verify again',()=>{
 const first=createSessionStore(services()),second=createSessionStore(services())
 assert.equal(first.getSnapshot().status,'checking');assert.equal(second.getSnapshot().status,'checking')
})

test('logout waits for confirmation, deduplicates clicks and removes access only on success',async()=>{
 const pending=deferred<{success:true}>();let calls=0
 const store=createSessionStore(services({logout(){calls++;return pending.promise}}))
 await store.verify()
 const first=store.logout(),second=store.logout()
 assert.equal(first,second)
 assert.equal(store.getSnapshot().status,'authenticated')
 await Promise.resolve();assert.equal(calls,1)
 pending.resolve({success:true});await first
 assert.equal(store.getSnapshot().status,'unauthenticated')
})

for(const error of [new AdminApiError('unavailable',503),new AdminApiError('network')]){
 test(`logout ${error.kind} preserves uncertainty and can retry`,async()=>{
  let calls=0
  const store=createSessionStore(services({async logout(){if(++calls===1)throw error;return {success:true}}}))
  await store.verify();await store.logout()
  const state=store.getSnapshot();assert.equal(state.status,'authenticated')
  if(state.status==='authenticated'){assert.equal(state.loggingOut,false);assert.match(state.message!,/não foi possível confirmar/i)}
  await store.logout();assert.equal(store.getSnapshot().status,'unauthenticated')
 })
}

test('protected HTTP 401 invalidates visual permission and discards stale verify',async()=>{
 const pending=deferred<AdminSession>()
 const store=createSessionStore(services({getSession(){return pending.promise}}))
 const request=store.verify()
 store.handleUnauthorized(new AdminApiError('invalid_session',401))
 pending.resolve(SESSION);await request
 assert.equal(store.getSnapshot().status,'unauthenticated')
})

test('old session response cannot resurrect session after logout',async()=>{
 const pending=deferred<AdminSession>();let calls=0
 const store=createSessionStore(services({getSession(){return ++calls===1?Promise.resolve(SESSION):pending.promise}}))
 await store.verify();const old=store.verify();await Promise.resolve()
 await store.logout();pending.resolve(SESSION);await old
 assert.equal(store.getSnapshot().status,'unauthenticated')
})

test('old initial failure cannot overwrite confirmed login',async()=>{
 const pending=deferred<AdminSession>();let calls=0
 const store=createSessionStore(services({getSession(){return ++calls===1?pending.promise:Promise.resolve(SESSION)}}))
 const old=store.verify();await Promise.resolve()
 await store.login({email:'x',password:'synthetic'});await store.confirmLogin()
 pending.reject(new AdminApiError('network'));await old
 assert.equal(store.getSnapshot().status,'authenticated')
})

test('stale login response after invalidation cannot confirm access',async()=>{
 const pending=deferred<{admin_id:string}>()
 const store=createSessionStore(services({login(){return pending.promise}}))
 const request=store.login({email:'x',password:'synthetic'})
 store.handleUnauthorized(new AdminApiError('invalid_session',401))
 pending.resolve({admin_id:'synthetic'})
 await assert.rejects(request)
 await assert.rejects(store.confirmLogin())
 assert.equal(store.getSnapshot().status,'unauthenticated')
})
