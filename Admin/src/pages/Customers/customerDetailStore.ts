import {AdminApiError, getAdminCustomer} from '../../services/adminApi.ts'
import type {AdminCustomer} from '../../services/adminApi.ts'

export interface CustomerDetailState {
  status: 'idle' | 'loading' | 'ready' | 'error' | 'forbidden' | 'not_found' | 'invalid'
  customer: AdminCustomer | null
  message?: string
}
export function createCustomerDetailStore(onUnauthorized:(error:unknown)=>void,
  fetchCustomer:(id:string)=>Promise<AdminCustomer> = getAdminCustomer) {
  let state:CustomerDetailState={status:'idle',customer:null}
  let identifier:string|undefined
  let generation=0
  let inFlight:Promise<void>|undefined
  const listeners=new Set<()=>void>()
  function publish(next:CustomerDetailState){state=next;listeners.forEach(listener=>listener())}
  function load(id:string, retry=false):Promise<void>{
    if(identifier===id && !retry)return inFlight??Promise.resolve()
    identifier=id
    const current=++generation
    publish({status:'loading',customer:null})
    const promise=(async()=>{
      try{
        const customer=await Promise.resolve().then(()=>current===generation?fetchCustomer(id):undefined)
        if(current===generation && customer)publish({status:'ready',customer})
      }catch(error){
        if(current!==generation)return
        const status=error instanceof AdminApiError?error.status:undefined
        if(status===401){onUnauthorized(error);if(current!==generation)return}
        publish({status:status===404?'not_found':status===403?'forbidden':status===400?'invalid':'error',customer:null,
          message:status===400?'Identificador de cliente inválido.':status===401?'Sessão administrativa ausente ou inválida.'
          :status===403?'Você não tem permissão para consultar este cliente.':status===404?'Cliente não encontrado.'
          :error instanceof AdminApiError && error.kind==='unavailable'?'Serviço administrativo indisponível.'
          :'Não foi possível consultar os dados do cliente. Tente novamente mais tarde.'})
      }finally{if(current===generation)inFlight=undefined}
    })()
    inFlight=promise
    return promise
  }
  return {
    getSnapshot:()=>state,
    subscribe(listener:()=>void){listeners.add(listener);return()=>{listeners.delete(listener)}},
    load,
    retry(){return identifier!==undefined && state.status==='error'?load(identifier,true):Promise.resolve()},
    clear(){generation++;identifier=undefined;inFlight=undefined;publish({status:'idle',customer:null})},
  }
}
