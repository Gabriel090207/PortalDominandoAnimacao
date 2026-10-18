import {AdminApiError, getAdminCustomers} from '../../services/adminApi.ts'
import type {AdminCustomer, AdminCustomerPage, CustomerQuery} from '../../services/adminApi.ts'

export interface CustomersState {
  status: 'idle' | 'loading' | 'ready' | 'error' | 'forbidden'
  items: AdminCustomer[]
  nextCursor: string | null
  canPrevious: boolean
  message?: string
}
const empty = (): CustomersState => ({status:'idle',items:[],nextCursor:null,canPrevious:false})

export function createCustomersStore(onUnauthorized: (error: unknown)=>void,
  fetchPage: (query: CustomerQuery)=>Promise<AdminCustomerPage> = getAdminCustomers) {
  let state=empty()
  const listeners=new Set<()=>void>()
  let generation=0
  let history: (string | undefined)[]=[undefined]
  let position=0
  let requested: {target:number;cursor:string|undefined}={target:0,cursor:undefined}
  let inFlight: Promise<void> | undefined
  function publish(next:CustomersState){state=next;listeners.forEach(listener=>listener())}
  function load(target:number,cursor:string | undefined):Promise<void>{
    if(inFlight)return inFlight
    const current=++generation
    requested={target,cursor}
    publish({status:'loading',items:[],nextCursor:null,canPrevious:position>0})
    const promise=(async()=>{
      try{
        const page=await Promise.resolve().then(()=>current===generation?fetchPage({limit:20,...(cursor===undefined?{}:{cursor})}):undefined)
        if(current!==generation||!page)return
        if(target>position)history=[...history.slice(0,target),cursor]
        position=target
        publish({status:'ready',items:page.items,nextCursor:page.next_cursor,canPrevious:position>0})
      }catch(error){
        if(current!==generation)return
        if(error instanceof AdminApiError && error.status===401){
          onUnauthorized(error)
          if(current===generation)publish({status:'error',items:[],nextCursor:null,canPrevious:false,message:'Sessão administrativa ausente ou inválida.'})
          return
        }
        const forbidden=error instanceof AdminApiError && error.status===403
        publish({status:forbidden?'forbidden':'error',items:[],nextCursor:null,canPrevious:position>0,
          message:forbidden?'Você não tem permissão para consultar os clientes.':error instanceof AdminApiError?error.message:'Não foi possível consultar os clientes. Tente novamente mais tarde.'})
      }finally{if(current===generation)inFlight=undefined}
    })()
    inFlight=promise
    return promise
  }
  return {
    getSnapshot:()=>state,
    subscribe(listener:()=>void){listeners.add(listener);return()=>{listeners.delete(listener)}},
    loadInitial(){if(state.status==='idle')return load(0,undefined);return inFlight??Promise.resolve()},
    next(){if(state.status!=='ready'||!state.nextCursor)return Promise.resolve();return load(position+1,state.nextCursor)},
    previous(){if(state.status==='loading'||position===0)return Promise.resolve();return load(position-1,history[position-1])},
    retry(){if(state.status==='loading'||state.status==='forbidden')return inFlight??Promise.resolve();return load(requested.target,requested.cursor)},
    clear(){generation++;inFlight=undefined;history=[undefined];position=0;requested={target:0,cursor:undefined};publish(empty())},
  }
}
