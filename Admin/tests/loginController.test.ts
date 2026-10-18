import {test} from 'node:test'
import assert from 'node:assert/strict'
import {createLoginController} from '../src/pages/Login/loginController.ts'
import type {LoginState} from '../src/pages/Login/loginController.ts'
import {AdminApiError} from '../src/services/adminApi.ts'
import type {AdminSession} from '../src/services/adminApi.ts'

const SESSION: AdminSession = {admin_id:'synthetic-admin',email:'admin@example.test',role:'operator',permissions:['read_customers']}

test('construction never authenticates; successful login requires session check', async () => {
  const states: LoginState[] = []
  const calls: string[] = []
  const controller = createLoginController({
    async login(credentials){calls.push('login');assert.equal(credentials.email,'invalid');return {admin_id:'synthetic-admin'}},
    async getSession(){calls.push('session');return SESSION},
  }, state => states.push(state))
  assert.deepEqual(calls,[])
  await controller.submit({email:'invalid',password:'synthetic-password'})
  assert.deepEqual(calls,['login','session'])
  assert.deepEqual(states.map(s=>s.phase),['submitting','checking','authenticated'])
  assert.equal(states.at(-1)?.session,SESSION)
  assert.ok(!JSON.stringify(states).includes('synthetic-password'))
})

test('simultaneous submissions never create multiple requests', async () => {
  let release!: () => void
  let calls = 0
  const wait = new Promise<void>(resolve=>{release=resolve})
  const controller = createLoginController({async login(){calls++;await wait;return {admin_id:'synthetic'}},async getSession(){return SESSION}},()=>{})
  const first = controller.submit({email:'x',password:'synthetic'})
  await controller.submit({email:'y',password:'different'})
  assert.equal(calls,1)
  release()
  await first
})

for(const kind of ['invalid_credentials','forbidden','rate_limited','unavailable','network','configuration'] as const){
  test(`safe feedback for ${kind}`,async()=>{
    const states: LoginState[] = []
    let sessions = 0
    const controller = createLoginController({async login(){throw new AdminApiError(kind,kind==='rate_limited'?429:undefined,kind==='rate_limited'?'60':undefined)},async getSession(){sessions++;return SESSION}},s=>states.push(s))
    await controller.submit({email:'x',password:'synthetic-secret'})
    assert.equal(states.at(-1)?.phase,'error')
    assert.equal(sessions,0)
    assert.ok(!JSON.stringify(states).includes('synthetic-secret'))
    if(kind==='rate_limited')assert.match(states.at(-1)!.message!,/60 segundos/)
  })
}

test('no invented wait and no raw error displayed',async()=>{
  for(const error of [new AdminApiError('rate_limited',429),new Error('synthetic-private-stack-password')]){
    const states: LoginState[]=[]
    const controller=createLoginController({async login(){throw error},async getSession(){return SESSION}},s=>states.push(s))
    await controller.submit({email:'x',password:'synthetic'})
    const message=states.at(-1)!.message!
    assert.ok(!message.includes('segundos'))
    assert.ok(!message.includes('synthetic-private'))
  }
})

test('failed session confirmation never claims logout or invents permissions, retry only on action',async()=>{
  const states: LoginState[]=[]
  let queries=0,logins=0
  const controller=createLoginController({async login(){logins++;return {admin_id:'synthetic'}},async getSession(){if(++queries===1)throw new AdminApiError('network');return SESSION}},s=>states.push(s))
  await controller.submit({email:'x',password:'synthetic'})
  assert.equal(states.at(-1)?.phase,'unconfirmed')
  assert.equal(states.at(-1)?.session,undefined)
  assert.equal(queries,1)
  await controller.submit({email:'x',password:'synthetic'})
  assert.equal(logins,1)
  await controller.retrySession()
  assert.equal(states.at(-1)?.phase,'authenticated')
  assert.equal(queries,2)
})
