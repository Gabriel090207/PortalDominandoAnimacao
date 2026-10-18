import {useEffect,useRef,useSyncExternalStore} from 'react'
import type {CustomerAccessStore} from './customerAccessStore'
export interface CustomerAccessText {
  label:string;trigger:string;legend:string;description:string;note:string;consent:string;confirm:string;submitting:string
}
export default function CustomerAccessAction({action,email,available,text,restriction=false}:{action:CustomerAccessStore;email?:string;available:boolean;text:CustomerAccessText;restriction?:boolean}){
  const state=useSyncExternalStore(action.subscribe,action.getSnapshot,action.getSnapshot)
  const trigger=useRef<HTMLButtonElement>(null),checkbox=useRef<HTMLInputElement>(null),feedback=useRef<HTMLParagraphElement>(null)
  const previous=useRef(state.status)
  useEffect(()=>{
    if(state.status==='confirming')checkbox.current?.focus()
    else if(previous.current==='confirming'&&state.status==='idle')trigger.current?.focus()
    else if(['confirmed','uncertain','error'].includes(state.status)||(state.status==='idle'&&state.message))feedback.current?.focus()
    previous.current=state.status
  },[state.status,state.message])
  if(state.status==='idle'&&!available&&!state.message)return null
  return <section className={`customer-activation${restriction?' customer-suspension':''}`} aria-label={text.label} aria-busy={state.status==='submitting'||state.status==='refreshing'}>
    {state.message&&<p ref={feedback} tabIndex={-1} role={state.status==='error'||state.status==='uncertain'?'alert':'status'}>{state.message}</p>}
    {(state.status==='idle'||state.status==='confirmed')&&available&&action.canOpen()&&<button ref={trigger} type="button" className="secondary-button" onClick={()=>action.open()}>{text.trigger}</button>}
    {state.status==='confirming'&&<form onSubmit={event=>{event.preventDefault();void action.submit()}}>
      <fieldset><legend>{text.legend}</legend><p>{text.description}</p><p className="activation-email">{email}</p>
        <p>{text.note}</p>
        <label className="activation-consent"><input ref={checkbox} type="checkbox" checked={state.consent} onChange={event=>action.consent(event.target.checked)}/>{text.consent}</label>
        <div className="activation-actions"><button type="button" className="secondary-button" onClick={()=>action.cancel()}>Cancelar</button><button type="submit" className="secondary-button" disabled={!state.consent||!available}>{text.confirm}</button></div>
      </fieldset></form>}
    {state.status==='submitting'&&<p role="status">{text.submitting}</p>}
    {state.status==='refreshing'&&<p role="status">Atualizando situação…</p>}
    {['error','uncertain','confirmed'].includes(state.status)&&<button type="button" className="secondary-button" onClick={()=>void action.refresh()}>Atualizar situação</button>}
  </section>
}
