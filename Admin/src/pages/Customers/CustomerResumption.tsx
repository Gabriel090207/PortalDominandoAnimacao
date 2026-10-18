import CustomerAccessAction from './CustomerAccessAction'
import type {CustomerResumptionStore} from './customerResumptionStore'
const text={label:'Retomada manual de acesso',trigger:'Retomar acesso',legend:'Retomar acesso do cliente',
  description:'Esta ação solicitará a retirada da suspensão administrativa.',
  note:'O acesso ao portal continuará dependendo das condições de compra e assinatura verificadas pelo sistema.',
  consent:'Confirmo que desejo retomar o acesso deste cliente.',
  confirm:'Confirmar retomada',submitting:'Retomando acesso…'}
export default function CustomerResumption({resumption,email,available}:{resumption:CustomerResumptionStore;email?:string;available:boolean}){
  return <CustomerAccessAction action={resumption} email={email} available={available} text={text}/>
}
