import {useEffect,useState,useSyncExternalStore} from 'react'
import type {SessionState,SessionStore} from '../../session/sessionStore'
import {createPurchaseConfirmationStore} from './purchaseConfirmationStore'
import type {PurchaseConfirmationStore} from './purchaseConfirmationStore'
type AuthenticatedState=Extract<SessionState,{status:'authenticated'}>
export function PurchaseConfirmationView({confirmationStore}:{confirmationStore:PurchaseConfirmationStore}){
  const state=useSyncExternalStore(confirmationStore.subscribe,confirmationStore.getSnapshot,confirmationStore.getSnapshot)
  const loading=state.status==='idle'||state.status==='loading'
  return <section className="purchase-confirmation" aria-label="Compra aprovada registrada" aria-busy={loading}>
    {loading?<p role="status">Consultando confirmação da compra…</p>
      :state.status==='ready'&&state.confirmation?<><p><strong>Compra aprovada registrada:</strong> {state.confirmation.approved_purchase_recorded?'Sim':'Não encontrada'}</p>
        <p className="purchase-note">Em caso de dúvida, confira a compra diretamente na Kirvano.</p></>
      :<><p role="alert">{state.message}</p>{state.status==='error'&&<button type="button" className="secondary-button" onClick={()=>void confirmationStore.retry()}>Consultar confirmação novamente</button>}</>}
  </section>
}
export default function PurchaseConfirmation({customerId,session,store}:{customerId:string;session:AuthenticatedState;store:SessionStore}){
  const [confirmation]=useState(()=>createPurchaseConfirmationStore(store.handleUnauthorized))
  useEffect(()=>store.subscribe(()=>{
    const current=store.getSnapshot()
    if(current.status!=='authenticated'||current.loggingOut||current.session!==session.session)confirmation.clear()
  }),[confirmation,store,session.session])
  useEffect(()=>{if(!session.loggingOut)void confirmation.load(customerId)},[confirmation,customerId,session.loggingOut,session.session])
  return <PurchaseConfirmationView confirmationStore={confirmation}/>
}
