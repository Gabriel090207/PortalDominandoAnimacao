import {Link} from 'react-router-dom'
import type {CustomersState} from './customersStore'
import {accountLabel,activationLabel,registrationDate} from './customerDisplay'

export function CustomersList({state,linkLabel="Ver detalhes do cliente"}:{state:CustomersState;linkLabel?:string}){
  return <ul className="customers-list">{state.items.map(customer=><li key={customer.customer_id} className="customer-card">
    <h2>{customer.email}</h2><Link className="back-link" to={`/clientes/${encodeURIComponent(customer.customer_id)}`}>{linkLabel}</Link><dl><dt>Identificador</dt><dd>{customer.customer_id}</dd>
      <dt>Estado da conta</dt><dd>{accountLabel(customer.account_status)}</dd>
      <dt>Ativação</dt><dd>{activationLabel(customer.activation_status)}</dd>
      <dt>Cadastro</dt><dd>{registrationDate(customer.created_at)}</dd></dl>
  </li>)}</ul>
}
