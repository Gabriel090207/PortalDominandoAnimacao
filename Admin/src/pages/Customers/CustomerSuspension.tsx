import CustomerAccessAction from './CustomerAccessAction'
import type {CustomerSuspensionStore} from './customerSuspensionStore'
const text={label:'Suspensão manual de acesso',trigger:'Suspender acesso',legend:'Suspender acesso do cliente',
  description:'Este cliente perderá temporariamente o acesso ao portal.',
  note:'A suspensão não cancela a assinatura na Kirvano.',
  consent:'Confirmo que desejo suspender o acesso deste cliente.',
  confirm:'Confirmar suspensão',submitting:'Suspendendo acesso…'}
export default function CustomerSuspension({suspension,email,available}:{suspension:CustomerSuspensionStore;email?:string;available:boolean}){
  return <CustomerAccessAction action={suspension} email={email} available={available} text={text} restriction/>
}
