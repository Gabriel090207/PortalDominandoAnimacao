import { test } from 'node:test'
import assert from 'node:assert/strict'
import { AxiosError, AxiosHeaders } from 'axios'
import type { AxiosAdapter, InternalAxiosRequestConfig } from 'axios'
import { AdminApiError, createAdminApi } from '../src/services/adminApi.ts'

const BASE = 'https://api.example.test'
const PRIVATE = 'synthetic-private-password'
function harness(data: unknown = { admin_id: 'synthetic-admin' }) {
  const calls: InternalAxiosRequestConfig[] = []
  const adapter: AxiosAdapter = async config => {
    calls.push(config)
    return { data, status: 200, statusText: 'OK', headers: {}, config }
  }
  return { api: createAdminApi(BASE, adapter), calls }
}

test('construction/import makes no requests', () => {
  const { calls } = harness()
  assert.equal(calls.length, 0)
})
test('login uses JSON, credentials and exact route, with no email syntax rejection', async () => {
  const { api, calls } = harness()
  assert.deepEqual(await api.login({email: 'invalid', password: PRIVATE}), {admin_id:'synthetic-admin'})
  assert.equal(calls.length, 1)
  const call = calls[0]!
  assert.equal(call.url, '/admin/auth/login')
  assert.equal(call.baseURL, BASE)
  assert.equal(call.withCredentials, true)
  assert.equal(call.method, 'post')
  assert.equal(call.headers.get('X-Admin-Request'), '1')
  assert.equal(call.headers.get('Content-Type'), 'application/json')
  assert.deepEqual(JSON.parse(call.data), { email:'invalid',password:PRIVATE })
  assert.equal(call.params, undefined)
  assert.equal(call.headers.has('Authorization'), false)
  assert.equal(call.headers.has('Origin'), false)
})
test('session GET and typed response without expires_at', async () => {
  const session = {admin_id:'synthetic-admin',email:'admin@example.test',role:'operator',permissions:['read_customers']}
  const {api,calls} = harness(session)
  assert.deepEqual(await api.getSession(), session)
  assert.equal(calls[0]!.url, '/admin/auth/session')
  assert.equal(calls[0]!.method, 'get')
  assert.equal(calls[0]!.withCredentials, true)
})
test('logout is POST without body/token and does not auto retry', async () => {
  const {api,calls} = harness({success:true})
  assert.deepEqual(await api.logout(), {success:true})
  assert.equal(calls.length, 1)
  assert.equal(calls[0]!.url, '/admin/auth/logout')
  assert.equal(calls[0]!.method, 'post')
  assert.equal(calls[0]!.data, undefined)
  assert.equal(calls[0]!.headers.get('X-Admin-Request'), '1')
  assert.equal(calls[0]!.headers.has('Authorization'), false)
})
for (const operation of ['login','getSession','logout'] as const) {
  for (const status of [400,401,403,413,415,422,429,503]) {
    test(`${operation} sanitizes ${status} and never retries`, async () => {
      let calls = 0
      const adapter: AxiosAdapter = async config => {
        calls++
        throw new AxiosError(PRIVATE, 'ERR_BAD_RESPONSE', config, undefined,
          { data:{detail:PRIVATE},status,statusText:PRIVATE,config,headers:new AxiosHeaders({'retry-after':'60'}) })
      }
      const api = createAdminApi(BASE, adapter)
      const result = operation === 'login' ? api.login({email:'x',password:PRIVATE}) : api[operation]()
      await assert.rejects(result, (error: unknown) => {
        assert.ok(error instanceof AdminApiError)
        assert.equal(error.status,status)
        assert.equal(error.retryAfter,'60')
        assert.ok(!JSON.stringify(error).includes(PRIVATE))
        assert.ok(!String(error).includes(PRIVATE))
        if (status === 401) assert.equal(error.kind, operation === 'login' ? 'invalid_credentials' : 'invalid_session')
        if (status === 503) assert.equal(error.kind,'unavailable')
        if (status === 429) assert.equal(error.kind,'rate_limited')
        assert.equal('config' in error,false)
        assert.equal('cause' in error,false)
        return true
      })
      assert.equal(calls,1)
    })
  }
}
test('network failure is not logout confirmation, no fabricated Retry-After', async () => {
  let calls = 0
  const api = createAdminApi(BASE, async config => {
    calls++
    throw new AxiosError(PRIVATE,'ERR_NETWORK',config)
  })
  await assert.rejects(api.logout(), (error: unknown) => {
    assert.ok(error instanceof AdminApiError)
    assert.equal(error.kind,'network')
    assert.equal(error.retryAfter,undefined)
    return true
  })
  assert.equal(calls,1)
})
for (const value of ['', 'http://localhost:8000','relative','https://user:password@api.example.test','https://api.example.test?token=x']) {
  test(`invalid API configuration rejected without transport: ${value.split('@').pop()}`, () => {
    assert.throws(() => createAdminApi(value), AdminApiError)
  })
}
test('unexpected successful response cannot confirm logout', async () => {
  const {api} = harness({ success:false, private:'synthetic-private' })
  await assert.rejects(api.logout(), (error: unknown) => {
    assert.ok(error instanceof AdminApiError)
    assert.equal(error.kind,'unexpected_response')
    return true
  })
})
test('projects only approved login fields', async () => {
  const {api} = harness({admin_id:'synthetic-admin', token:'synthetic-private'})
  assert.deepEqual(await api.login({email:'x',password:PRIVATE}), {admin_id:'synthetic-admin'})
})

test('customers uses same credentialed client, GET and cursor query only',async()=>{
  const item={customer_id:'customer-a',email:'customer@example.test',account_status:'enabled',activation_status:'pending',created_at:'2026-01-01T10:00:00Z'}
  const {api,calls}=harness({items:[{...item,private:'synthetic-private'}],next_cursor:'Yg'})
  assert.deepEqual(await api.getCustomers({cursor:'YQ'}),{items:[item],next_cursor:'Yg'})
  const call=calls[0]!
  assert.equal(call.url,'/admin/customers');assert.equal(call.method,'get');assert.equal(call.withCredentials,true)
  assert.deepEqual(call.params,{limit:20,cursor:'YQ'})
  assert.equal(call.data,undefined);assert.equal(call.headers.has('Authorization'),false)
})
test('customers empty page and invalid limit',async()=>{
  const {api,calls}=harness({items:[],next_cursor:null})
  assert.deepEqual(await api.getCustomers(),{items:[],next_cursor:null})
  await assert.rejects(api.getCustomers({limit:51}),AdminApiError)
  assert.equal(calls.length,1)
})
test('customers HTTP 401 is a session error with no raw data',async()=>{
  const api=createAdminApi(BASE,async config=>{throw new AxiosError(PRIVATE,'ERR_BAD_RESPONSE',config,undefined,
    {data:{detail:PRIVATE},status:401,statusText:'Unauthorized',headers:{},config})})
  await assert.rejects(api.getCustomers(),(error:unknown)=>{
    assert.ok(error instanceof AdminApiError);assert.equal(error.kind,'invalid_session');assert.ok(!String(error).includes(PRIVATE));return true
  })
})
