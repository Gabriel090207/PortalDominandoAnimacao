import {useEffect,useState,useSyncExternalStore} from 'react'
import type {SessionState,SessionStore} from '../../session/sessionStore'
import {createCustomerLookupStore} from './customerLookupStore'
import type {CustomerLookupStore} from './customerLookupStore'
import {CustomersList} from './CustomersList'

type AuthenticatedState=Extract<SessionState,{status:'authenticated'}>
export function CustomerLookupForm({lookup,disabled=false}:{lookup:CustomerLookupStore;disabled?:boolean}){
  const state=useSyncExternalStore(lookup.subscribe,lookup.getSnapshot,lookup.getSnapshot)
  const loading=state.status==='loading'
  return <section className="customer-search" aria-labelledby="customer-search-title" aria-busy={loading}>
    <h2 id="customer-search-title">Buscar cliente</h2>
    <form noValidate onSubmit={event=>{event.preventDefault();if(!disabled)void lookup.search()}}>
      <div className="customer-search-field"><label htmlFor="customer-search-email">E-mail utilizado na compra</label>
        <input id="customer-search-email" type="email" autoComplete="off" spellCheck={false} value={state.email} disabled={disabled}
          onChange={event=>lookup.edit(event.target.value)}/></div>
      <div className="customer-search-actions"><button type="submit" className="secondary-button" disabled={disabled||loading||!state.email.trim()}>{loading?'Pesquisando…':'Pesquisar'}</button>
        {(state.email||state.status!=='idle')&&<button type="button" className="secondary-button" disabled={disabled} onClick={()=>lookup.clear()}>Limpar</button>}</div>
    </form>
    {loading&&<p role="status" aria-live="polite">Pesquisando cliente…</p>}
    {state.message&&<p role={state.status==='not_found'?'status':'alert'}>{state.message}</p>}
    {state.status==='found'&&state.customer&&<><p role="status">Cliente encontrado.</p><CustomersList linkLabel="Ver cliente" state={{status:'ready',items:[state.customer],nextCursor:null,canPrevious:false}}/></>}
  </section>
}
export default function CustomerLookup({session,store}:{session:AuthenticatedState;store:SessionStore}){
  const [lookup]=useState(()=>createCustomerLookupStore(store.handleUnauthorized))
  useEffect(()=>store.subscribe(()=>{
    const current=store.getSnapshot()
    if(current.status!=='authenticated'||current.loggingOut||current.session!==session.session)lookup.clear()
  }),[lookup,store,session.session])
  return <CustomerLookupForm lookup={lookup} disabled={session.loggingOut}/>
}
