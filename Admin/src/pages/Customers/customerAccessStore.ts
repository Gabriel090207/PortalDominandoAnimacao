import {AdminApiError} from '../../services/adminApi.ts'
import type {CustomerOperationCoordinator} from './customerOperationCoordinator.ts'

export interface CustomerAccessState {
  status:'idle'|'confirming'|'submitting'|'refreshing'|'confirmed'|'error'|'uncertain'
  consent:boolean
  message?:string
}
const empty=():CustomerAccessState=>({status:'idle',consent:false})
export function createCustomerAccessStore(customerId:string,options:{
  canRun:()=>boolean
  onUnauthorized:(error:unknown)=>void
  refresh:()=>Promise<void>
  perform:(id:string)=>Promise<{result:string}>
  messages:{uncertain:string;confirmed:(result:string)=>string;forbidden:string;conflict:string;invalid:string}
  coordinator?:CustomerOperationCoordinator
}){
  const owner=Symbol()
  const uncertain=options.messages.uncertain
  const release=()=>options.coordinator?.release(owner)
  const acquire=()=>options.coordinator?.acquire(owner)!==false
  let state=empty(),generation=0
  let inFlight:Promise<void>|undefined
  let committedMessage:string|undefined
  const listeners=new Set<()=>void>()
  function publish(next:CustomerAccessState){state=next;listeners.forEach(listener=>listener())}
  async function readBack(current:number,confirmedMessage?:string){
    try{
      await options.refresh()
      if(current!==generation)return
      release()
      publish({status:confirmedMessage?'confirmed':'idle',consent:false,
        message:confirmedMessage??'Situação atualizada. Confira os dados antes de uma nova tentativa.'})
    }catch(error){
      if(current!==generation)return
      if(error instanceof AdminApiError&&error.status===401){options.onUnauthorized(error);if(current!==generation)return}
      publish({status:confirmedMessage?'confirmed':'uncertain',consent:false,
        message:confirmedMessage?`${confirmedMessage} Não foi possível atualizar a ficha. Atualize a situação do cliente.`:uncertain})
    }
  }
  return {
    getSnapshot:()=>state,
    subscribe(listener:()=>void){listeners.add(listener);return()=>{listeners.delete(listener)}},
    open(){if(state.status==='idle'&&options.canRun()&&acquire())publish({status:'confirming',consent:false})},
    consent(value:boolean){if(state.status==='confirming')publish({...state,consent:value===true})},
    cancel(){if(state.status==='confirming'){release();publish(empty())}},
    submit():Promise<void>{
      if(inFlight)return inFlight
      if(state.status!=='confirming'||!state.consent||!options.canRun()||!acquire())return Promise.resolve()
      const current=++generation
      publish({status:'submitting',consent:false})
      const promise=(async()=>{
        try{
          // Recheck after the microtask boundary so logout before dispatch prevents POST.
          const result=await Promise.resolve().then(()=>current===generation&&options.canRun()?
            options.perform(customerId):undefined)
          if(current!==generation)return
          if(!result){release();publish(empty());return}
          const message=options.messages.confirmed(result.result)
          committedMessage=message
          publish({status:'refreshing',consent:false,message})
          await readBack(current,message)
        }catch(error){
          if(current!==generation)return
          const status=error instanceof AdminApiError?error.status:undefined
          if(status===401){options.onUnauthorized(error);if(current!==generation)return}
          const known=status!==undefined&&[400,401,403,404,409,413,415,422].includes(status)
          publish({status:known?'error':'uncertain',consent:false,message:!known?uncertain:
            status===401?'Sessão administrativa ausente ou inválida.':status===403?options.messages.forbidden
            :status===404?'Cliente não encontrado.':status===409?options.messages.conflict
            :options.messages.invalid})
        }finally{if(current===generation)inFlight=undefined}
      })()
      inFlight=promise;return promise
    },
    refresh():Promise<void>{
      if(inFlight)return inFlight
      if(!['error','uncertain','confirmed'].includes(state.status))return Promise.resolve()
      if(!acquire())return Promise.resolve()
      const confirmedMessage=state.status==='confirmed'?committedMessage:undefined
      const current=++generation
      publish({status:'refreshing',consent:false,message:confirmedMessage})
      const promise=readBack(current,confirmedMessage).finally(()=>{if(current===generation)inFlight=undefined})
      inFlight=promise;return promise
    },
    clear(){release();generation++;inFlight=undefined;committedMessage=undefined;publish(empty())},
  }
}
export type CustomerAccessStore=ReturnType<typeof createCustomerAccessStore>
