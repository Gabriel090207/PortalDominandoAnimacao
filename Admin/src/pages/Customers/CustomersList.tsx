import {Link} from 'react-router-dom'
import type {CustomersState} from './customersStore'
import {registrationDate} from './customerDisplay'
import {FiArrowRight} from 'react-icons/fi'
import CustomerStatus from './CustomerStatus'

export function CustomersList({state,linkLabel="Ver detalhes do cliente"}:{state:CustomersState;linkLabel?:string}){
  return <ul className="customers-list">{state.items.map(customer=><li key={customer.customer_id} className="customer-card">
    <h2>{customer.email}</h2><Link className="back-link" to={`/clientes/${encodeURIComponent(customer.customer_id)}`}><FiArrowRight aria-hidden="true"/>{linkLabel}</Link><dl><dt>Identificador</dt><dd>{customer.customer_id}</dd>
      <dt>Estado da conta</dt><dd><CustomerStatus kind="account" value={customer.account_status}/></dd>
      <dt>Ativação</dt><dd><CustomerStatus kind="activation" value={customer.activation_status}/></dd>
      <dt>Cadastro</dt><dd>{registrationDate(customer.created_at)}</dd></dl>
  </li>)}</ul>
}
