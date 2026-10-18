import {useEffect,useState,useSyncExternalStore} from 'react'
import {Link,useParams} from 'react-router-dom'
import {FiArrowLeft} from 'react-icons/fi'
import {AdminApiError} from '../../services/adminApi'
import type {AdminCustomer} from '../../services/adminApi'
import type {SessionState,SessionStore} from '../../session/sessionStore'
import {createCustomerDetailStore} from './customerDetailStore'
import {accountLabel,activationLabel,registrationDate} from './customerDisplay'
import {PurchaseConfirmationView} from './PurchaseConfirmation'
import {createPurchaseConfirmationStore} from './purchaseConfirmationStore'
import {createCustomerActivationStore,canActivateCustomer} from './customerActivationStore'
import CustomerActivation from './CustomerActivation'
import CustomerSuspension from './CustomerSuspension'
import CustomerResumption from './CustomerResumption'
import {createCustomerResumptionStore,canResumeCustomer} from './customerResumptionStore'
import {createCustomerSuspensionStore,canSuspendCustomer} from './customerSuspensionStore'
import {createCustomerOperationCoordinator} from './customerOperationCoordinator'
import './Customers.css'

type AuthenticatedState=Extract<SessionState,{status:'authenticated'}>
export function CustomerFacts({customer}:{customer:AdminCustomer}){
  return <dl className="customer-facts"><dt>E-mail</dt><dd>{customer.email}</dd>
    <dt>Identificador do cliente</dt><dd>{customer.customer_id}</dd>
    <dt>Situação da conta</dt><dd>{accountLabel(customer.account_status)}</dd>
    <dt>Status de ativação</dt><dd>{activationLabel(customer.activation_status)}</dd>
    <dt>Data de cadastro</dt><dd>{registrationDate(customer.created_at)}</dd></dl>
}
export default function CustomerDetail({session,store}:{session:AuthenticatedState;store:SessionStore}){
  const {customerId=''}=useParams()
  // A new ID/session gets an empty store immediately, before effects or old replies.
  return <CustomerDetailPage key={`${session.session.admin_id}:${customerId}`} customerId={customerId} session={session} store={store}/>
}
function CustomerDetailPage({customerId,session,store}:{customerId:string;session:AuthenticatedState;store:SessionStore}){
  const [detail]=useState(()=>createCustomerDetailStore(store.handleUnauthorized))
  const [confirmation]=useState(()=>createPurchaseConfirmationStore(store.handleUnauthorized))
  const [coordinator]=useState(createCustomerOperationCoordinator)
  const [activation]=useState(()=>createCustomerActivationStore(customerId,{
    coordinator,onUnauthorized:store.handleUnauthorized,
    canActivate:()=>{
      const customer=detail.getSnapshot(),purchase=confirmation.getSnapshot()
      return customer.status==='ready'&&purchase.status==='ready'&&canActivateCustomer(customer.customer,purchase.confirmation,store.getSnapshot())
    },
    refresh:async()=>{
      confirmation.clear()
      await detail.load(customerId,true)
      if(detail.getSnapshot().status!=='ready')throw new AdminApiError('unavailable')
    },
  }))
  const [suspension]=useState(()=>createCustomerSuspensionStore(customerId,{
    coordinator,onUnauthorized:store.handleUnauthorized,
    canSuspend:()=>{
      const customer=detail.getSnapshot()
      return customer.status==='ready'&&canSuspendCustomer(customer.customer,store.getSnapshot())
    },
    refresh:async()=>{
      // Restriction does not change the already fetched commercial information.
      await detail.load(customerId,true)
      if(detail.getSnapshot().status!=='ready')throw new AdminApiError('unavailable')
    },
  }))
  const [resumption]=useState(()=>createCustomerResumptionStore(customerId,{
    coordinator,onUnauthorized:store.handleUnauthorized,
    canResume:()=>{
      const customer=detail.getSnapshot()
      return customer.status==='ready'&&canResumeCustomer(customer.customer,store.getSnapshot())
    },
    refresh:async()=>{
      await detail.load(customerId,true)
      if(detail.getSnapshot().status!=='ready')throw new AdminApiError('unavailable')
    },
  }))
  const resumptionState=useSyncExternalStore(resumption.subscribe,resumption.getSnapshot,resumption.getSnapshot)
  const operation=useSyncExternalStore(coordinator.subscribe,coordinator.getSnapshot,coordinator.getSnapshot)
  const activationState=useSyncExternalStore(activation.subscribe,activation.getSnapshot,activation.getSnapshot)
  const suspensionState=useSyncExternalStore(suspension.subscribe,suspension.getSnapshot,suspension.getSnapshot)
  const state=useSyncExternalStore(detail.subscribe,detail.getSnapshot,detail.getSnapshot)
  const purchase=useSyncExternalStore(confirmation.subscribe,confirmation.getSnapshot,confirmation.getSnapshot)
  useEffect(()=>store.subscribe(()=>{
    const current=store.getSnapshot()
    if(current.status!=='authenticated'||current.loggingOut||current.session!==session.session){detail.clear();confirmation.clear();activation.clear();suspension.clear();resumption.clear()}
  }),[store,detail,confirmation,activation,suspension,resumption,session.session])
  useEffect(()=>{if(!session.loggingOut)void detail.load(customerId)},[detail,customerId,session.loggingOut,session.session])
  useEffect(()=>()=>{activation.clear();suspension.clear();resumption.clear();detail.clear();confirmation.clear()},[activation,suspension,resumption,detail,confirmation])
  useEffect(()=>{
    if(state.status==='ready'&&!session.loggingOut)void confirmation.load(customerId)
  },[state.status,confirmation,customerId,session.loggingOut,session.session])
  const resumptionAvailable=state.status==='ready'&&canResumeCustomer(state.customer,session)&&(operation===undefined||resumptionState.status!=='idle')
  const suspensionAvailable=state.status==='ready'&&canSuspendCustomer(state.customer,session)&&(operation===undefined||suspensionState.status!=='idle')
  const available=(operation===undefined||activationState.status!=='idle')&&state.status==='ready'&&purchase.status==='ready'&&canActivateCustomer(state.customer,purchase.confirmation,session)
  const loading=session.loggingOut||state.status==='idle'||state.status==='loading'
  return <main className="customers-page">
    <header className="customers-header"><div><Link to="/clientes" className="back-link"><FiArrowLeft aria-hidden="true"/> Voltar à listagem</Link><h1>Detalhes do cliente</h1><Link to="/painel" className="back-link">Voltar ao painel</Link></div>
      <button type="button" className="secondary-button" disabled={session.loggingOut} onClick={()=>void store.logout()}>{session.loggingOut?'Encerrando sessão…':'Sair'}</button></header>
    {session.message&&<p className="feedback" role="alert">{session.message}</p>}
    <section className="customer-card" aria-label="Ficha do cliente" aria-busy={loading}>
      {loading?<p role="status">Consultando cliente…</p>:state.status==='ready'&&state.customer?<><CustomerFacts customer={state.customer}/><PurchaseConfirmationView confirmationStore={confirmation}/></>
        :<><p role="alert">{state.message}</p>{state.status==='error'&&<button type="button" className="secondary-button" onClick={()=>void detail.retry()}>Tentar novamente</button>}</>}
    </section>
    {!session.loggingOut&&<CustomerResumption resumption={resumption} email={state.customer?.email} available={resumptionAvailable}/>}
    {!session.loggingOut&&<CustomerSuspension suspension={suspension} email={state.customer?.email} available={suspensionAvailable}/>}
    {!session.loggingOut&&<CustomerActivation activation={activation} email={state.customer?.email} available={available}/>}
  </main>
}
