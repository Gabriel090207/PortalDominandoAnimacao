import {suspendAdminCustomer} from '../../services/adminApi.ts'
import type {AdminCustomer,CustomerSuspensionResult} from '../../services/adminApi.ts'
import type {SessionState} from '../../session/sessionStore.ts'
import {createCustomerAccessStore} from './customerAccessStore.ts'
import type {CustomerOperationCoordinator} from './customerOperationCoordinator.ts'

export function canSuspendCustomer(customer:AdminCustomer|null,session:SessionState){
  return session.status==='authenticated'&&!session.loggingOut
    &&session.session.permissions.includes('read_customers')
    &&session.session.permissions.includes('suspend_customer')
    &&customer?.account_status==='enabled'&&customer.activation_status==='active'
}
export function createCustomerSuspensionStore(customerId:string,options:{
  canSuspend:()=>boolean
  onUnauthorized:(error:unknown)=>void
  refresh:()=>Promise<void>
  suspend?:(id:string)=>Promise<CustomerSuspensionResult>
  coordinator?:CustomerOperationCoordinator
}){
  return createCustomerAccessStore(customerId,{
    ...options,canRun:options.canSuspend,perform:options.suspend??suspendAdminCustomer,
    messages:{
      uncertain:'Não foi possível confirmar o resultado da suspensão. Atualize a situação do cliente antes de tentar novamente.',
      confirmed:result=>result==='suspended'?'Acesso suspenso com sucesso.':'Este cliente já está suspenso.',
      forbidden:'Acesso negado à suspensão.',conflict:'Não foi possível suspender este cliente nas condições atuais.',
      invalid:'Não foi possível enviar a suspensão. Requisição inválida.',
    },
  })
}
export type CustomerSuspensionStore=ReturnType<typeof createCustomerSuspensionStore>
