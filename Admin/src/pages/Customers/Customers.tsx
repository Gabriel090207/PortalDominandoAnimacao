import {useEffect,useState,useSyncExternalStore} from 'react'
import {Link} from 'react-router-dom'
import type {SessionState,SessionStore} from '../../session/sessionStore'
import {createCustomersStore} from './customersStore'
import {CustomersList} from './CustomersList'
export {CustomersList} from './CustomersList'
import CustomerLookup from './CustomerLookup'
import './Customers.css'

type AuthenticatedState=Extract<SessionState,{status:'authenticated'}>
export default function Customers({session,store}:{session:AuthenticatedState;store:SessionStore}){
  const [customers]=useState(()=>createCustomersStore(store.handleUnauthorized))
  const state=useSyncExternalStore(customers.subscribe,customers.getSnapshot,customers.getSnapshot)
  useEffect(()=>store.subscribe(()=>{
    const current=store.getSnapshot()
    if(current.status!=='authenticated'||current.loggingOut||current.session!==session.session)customers.clear()
  }),[store,customers,session.session])
  useEffect(()=>{if(!session.loggingOut)void customers.loadInitial()},[customers,session.loggingOut])
  const loading=state.status==='loading'||state.status==='idle'||session.loggingOut
  return <main className="customers-page">
    <header className="customers-header"><div><Link to="/painel" className="back-link">← Voltar ao painel</Link><h1>Clientes</h1><p>Consulta dos clientes cadastrados no portal.</p></div>
      <button type="button" className="secondary-button" disabled={session.loggingOut} onClick={()=>void store.logout()}>{session.loggingOut?'Encerrando sessão…':'Sair'}</button></header>
    {session.message&&<p className="feedback" role="alert">{session.message}</p>}
    <CustomerLookup session={session} store={store}/>
    <section aria-label="Listagem de clientes" aria-busy={loading}>
      {loading?<p role="status" className="customers-notice">Consultando clientes…</p>
        :state.status==='error'||state.status==='forbidden'?<div className="customers-notice"><p role="alert">{state.message}</p>{state.status==='error'&&<button type="button" className="secondary-button" onClick={()=>void customers.retry()}>Tentar novamente</button>}</div>
        :state.items.length===0?<p className="customers-notice" role="status">Nenhum cliente encontrado.</p>:<CustomersList state={state}/>}
      <nav className="customers-pagination" aria-label="Paginação de clientes"><button type="button" className="secondary-button" disabled={loading||!state.canPrevious||state.status==='forbidden'} onClick={()=>void customers.previous()}>Anterior</button><span>Até 20 clientes por consulta</span><button type="button" className="secondary-button" disabled={loading||state.status!=='ready'||!state.nextCursor} onClick={()=>void customers.next()}>Próxima</button></nav>
    </section>
  </main>
}
