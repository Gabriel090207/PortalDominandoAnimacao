import {Link} from 'react-router-dom'
import type { SessionState, SessionStore } from '../../session/sessionStore'

type AuthenticatedState = Extract<SessionState, {status: 'authenticated'}>
export default function Panel({state, store}: {state: AuthenticatedState; store: SessionStore}) {
  return <div className="login-shell"><main className="login-layout"><section className="login-card" aria-labelledby="panel-title">
    <p className="card-eyebrow">DOMINANDO ANIMAÇÃO · ADMIN</p>
    <h1 id="panel-title">Painel administrativo</h1>
    <p className="card-description">Sessão confirmada pelo servidor.</p>
    <dl className="session-details"><dt>Administrador</dt><dd>{state.session.admin_id}</dd><dt>E-mail</dt><dd>{state.session.email}</dd><dt>Papel</dt><dd>{state.session.role === 'owner' ? 'Proprietário (owner)' : 'Operador (operator)'}</dd></dl>
    {state.session.permissions.includes('read_customers')&&<Link className="panel-link" to="/clientes">Clientes →</Link>}
    {state.message && <p className="feedback" role="alert">{state.message}</p>}
    <button className="submit-button" type="button" disabled={state.loggingOut} onClick={() => void store.logout()}>{state.loggingOut ? 'Encerrando sessão…' : 'Sair'}</button>
    <p className="form-help">As permissões de cada operação continuam sendo verificadas pelo backend.</p>
  </section></main></div>
}
