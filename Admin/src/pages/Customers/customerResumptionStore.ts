import {resumeAdminCustomer} from '../../services/adminApi.ts'
import type {AdminCustomer,CustomerResumptionResult} from '../../services/adminApi.ts'
import type {SessionState} from '../../session/sessionStore.ts'
import {createCustomerAccessStore} from './customerAccessStore.ts'
import type {CustomerOperationCoordinator} from './customerOperationCoordinator.ts'

export function canResumeCustomer(customer:AdminCustomer|null,session:SessionState){
  return session.status==='authenticated'&&!session.loggingOut
    &&session.session.permissions.includes('read_customers')
    &&session.session.permissions.includes('resume_customer')
    &&customer?.account_status==='enabled'&&customer.activation_status==='suspended'
}
export function createCustomerResumptionStore(customerId:string,options:{
  canResume:()=>boolean
  onUnauthorized:(error:unknown)=>void
  refresh:()=>Promise<void>
  resume?:(id:string)=>Promise<CustomerResumptionResult>
  coordinator?:CustomerOperationCoordinator
}){
  return createCustomerAccessStore(customerId,{
    ...options,canRun:options.canResume,perform:options.resume??resumeAdminCustomer,
    messages:{
      uncertain:'Não foi possível confirmar o resultado da retomada. Atualize a situação do cliente antes de tentar novamente.',
      confirmed:result=>result==='resumed'?'Acesso retomado com sucesso.':'Este cliente já está ativo.',
      forbidden:'Acesso negado à retomada.',conflict:'Não foi possível retomar o acesso nas condições atuais. Verifique a situação do cliente antes de tentar novamente.',
      invalid:'Não foi possível enviar a retomada. Requisição inválida.',
    },
  })
}
export type CustomerResumptionStore=ReturnType<typeof createCustomerResumptionStore>
