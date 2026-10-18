import CustomerAccessAction from './CustomerAccessAction'
import type {CustomerActivationStore} from './customerActivationStore'
const text={label:'Ativação manual',trigger:'Ativar acesso',legend:'Confirmar ativação manual',
  description:'Você está prestes a ativar o acesso deste cliente.',
  note:'O acesso será permitido caso as demais regras sejam atendidas. Confirme que verificou as informações da compra. Em caso de dúvida, confira diretamente na Kirvano.',
  consent:'Conferi as informações do comprador e autorizo a ativação do acesso.',
  confirm:'Confirmar ativação',submitting:'Ativando acesso…'}
export default function CustomerActivation({activation,email,available}:{activation:CustomerActivationStore;email?:string;available:boolean}){
  return <CustomerAccessAction action={activation} email={email} available={available} text={text}/>
}
