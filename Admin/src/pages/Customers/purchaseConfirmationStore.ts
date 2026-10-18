import {AdminApiError,getAdminPurchaseConfirmation} from '../../services/adminApi.ts'
import type {AdminPurchaseConfirmation} from '../../services/adminApi.ts'
export interface PurchaseConfirmationState {
  status:'idle'|'loading'|'ready'|'error'|'forbidden'|'not_found'
  confirmation:AdminPurchaseConfirmation|null
  message?:string
}
export function createPurchaseConfirmationStore(onUnauthorized:(error:unknown)=>void,
  fetchConfirmation:(id:string)=>Promise<AdminPurchaseConfirmation>=getAdminPurchaseConfirmation){
  let state:PurchaseConfirmationState={status:'idle',confirmation:null}
  let identifier:string|undefined,generation=0,inFlight:Promise<void>|undefined
  const listeners=new Set<()=>void>()
  function publish(next:PurchaseConfirmationState){state=next;listeners.forEach(listener=>listener())}
  function load(id:string,retry=false):Promise<void>{
    if(identifier===id&&!retry)return inFlight??Promise.resolve()
    identifier=id;const current=++generation
    publish({status:'loading',confirmation:null})
    const promise=(async()=>{
      try{
        const confirmation=await Promise.resolve().then(()=>current===generation?fetchConfirmation(id):undefined)
        if(current===generation&&confirmation)publish({status:'ready',confirmation})
      }catch(error){
        if(current!==generation)return
        const status=error instanceof AdminApiError?error.status:undefined
        if(status===401){onUnauthorized(error);if(current!==generation)return}
        publish({status:status===403?'forbidden':status===404?'not_found':'error',confirmation:null,
          message:status===401?'Sessão administrativa ausente ou inválida.'
            :status===403?'Acesso negado à confirmação da compra.'
            :status===404?'Cliente não encontrado.'
            :'Não foi possível consultar a confirmação da compra.'})
      }finally{if(current===generation)inFlight=undefined}
    })()
    inFlight=promise;return promise
  }
  return {
    getSnapshot:()=>state,
    subscribe(listener:()=>void){listeners.add(listener);return()=>{listeners.delete(listener)}},
    load,
    retry(){return identifier!==undefined&&state.status==='error'?load(identifier,true):Promise.resolve()},
    clear(){generation++;identifier=undefined;inFlight=undefined;publish({status:'idle',confirmation:null})},
  }
}
export type PurchaseConfirmationStore=ReturnType<typeof createPurchaseConfirmationStore>
