import {AdminApiError,lookupAdminCustomer} from '../../services/adminApi.ts'
import type {AdminCustomer} from '../../services/adminApi.ts'
export interface CustomerLookupState {
  email:string
  status:'idle'|'loading'|'found'|'not_found'|'ambiguous'|'error'
  customer:AdminCustomer|null
  message?:string
}
const empty=():CustomerLookupState=>({email:'',status:'idle',customer:null})
export function createCustomerLookupStore(onUnauthorized:(error:unknown)=>void,
  lookup:(email:string)=>Promise<AdminCustomer>=lookupAdminCustomer){
  let state=empty(),generation=0
  let inFlight:Promise<void>|undefined
  const listeners=new Set<()=>void>()
  function publish(next:CustomerLookupState){state=next;listeners.forEach(listener=>listener())}
  function reset(email:string){generation++;inFlight=undefined;publish({...empty(),email})}
  return {
    getSnapshot:()=>state,
    subscribe(listener:()=>void){listeners.add(listener);return()=>{listeners.delete(listener)}},
    edit(email:string){if(email!==state.email)reset(email)},
    clear(){reset('')},
    search():Promise<void>{
      if(inFlight)return inFlight
      if(!state.email.trim()){
        publish({...state,status:'error',customer:null,message:'Informe o e-mail utilizado na compra.'})
        return Promise.resolve()
      }
      const current=++generation,email=state.email
      publish({email,status:'loading',customer:null})
      const promise=(async()=>{
        try{
          const customer=await Promise.resolve().then(()=>current===generation?lookup(email):undefined)
          if(current===generation&&customer)publish({email,status:'found',customer})
        }catch(error){
          if(current!==generation)return
          const status=error instanceof AdminApiError?error.status:undefined
          if(status===401){onUnauthorized(error);if(current!==generation)return}
          const message=status===404?'Nenhum cliente encontrado com esse e-mail.'
            :status===409?'Existem cadastros associados a esse e-mail que precisam de verificação administrativa.'
            :status===401?'Sessão administrativa ausente ou inválida.'
            :status===403?'Requisição administrativa não autorizada.'
            :[400,413,415,422].includes(status??0)?'Não foi possível realizar a pesquisa. Verifique o e-mail informado.'
            :error instanceof AdminApiError&&error.kind==='unavailable'?'Serviço administrativo indisponível.'
            :error instanceof AdminApiError&&error.kind==='network'?'Não foi possível consultar o servidor.'
            :'Não foi possível pesquisar o cliente. Tente novamente mais tarde.'
          publish({email,status:status===404?'not_found':status===409?'ambiguous':'error',customer:null,message})
        }finally{if(current===generation)inFlight=undefined}
      })()
      inFlight=promise;return promise
    },
  }
}
export type CustomerLookupStore=ReturnType<typeof createCustomerLookupStore>
