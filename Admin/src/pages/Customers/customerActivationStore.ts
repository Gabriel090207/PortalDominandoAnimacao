import {activateAdminCustomer} from '../../services/adminApi.ts'
import type {AdminCustomer,AdminPurchaseConfirmation,CustomerActivationResult} from '../../services/adminApi.ts'
import type {SessionState} from '../../session/sessionStore.ts'
import {createCustomerAccessStore} from './customerAccessStore.ts'
import type {CustomerAccessState} from './customerAccessStore.ts'
import type {CustomerOperationCoordinator} from './customerOperationCoordinator.ts'


export function canActivateCustomer(customer:AdminCustomer|null,confirmation:AdminPurchaseConfirmation|null,session:SessionState){
  return session.status==='authenticated'&&!session.loggingOut&&session.session.permissions.includes('read_customers')
    &&session.session.permissions.includes('activate_customer')&&customer?.activation_status==='pending'
    &&customer.account_status==='enabled'&&confirmation?.customer_id===customer.customer_id
    &&confirmation.approved_purchase_recorded===true
}

export function createCustomerActivationStore(customerId:string,options:{
  canActivate:()=>boolean
  onUnauthorized:(error:unknown)=>void
  refresh:()=>Promise<void>
  activate?:(id:string)=>Promise<CustomerActivationResult>
  coordinator?:CustomerOperationCoordinator
}){
  return createCustomerAccessStore(customerId,{
    ...options,canRun:options.canActivate,perform:options.activate??activateAdminCustomer,
    messages:{
      uncertain:'Não foi possível confirmar o resultado da ativação. Atualize a situação do cliente antes de tentar novamente.',
      confirmed:result=>result==='activated'?'Acesso ativado com sucesso.':'Este cliente já está ativo.',
      forbidden:'Acesso negado à ativação.',conflict:'Não foi possível ativar este cliente nas condições atuais.',
      invalid:'Não foi possível enviar a ativação. Requisição inválida.',
    },
  })
}
export type CustomerActivationState=CustomerAccessState
export type CustomerActivationStore=ReturnType<typeof createCustomerActivationStore>
