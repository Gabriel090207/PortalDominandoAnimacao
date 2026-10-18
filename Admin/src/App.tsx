import { useEffect, useState, useSyncExternalStore } from 'react'
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom'
import Login from './pages/Login/Login'
import Panel from './pages/Panel/Panel'
import Customers from './pages/Customers/Customers'
import CustomerDetail from './pages/Customers/CustomerDetail'
import { createSessionStore } from './session/sessionStore'
import type { SessionStore } from './session/sessionStore'

export function SessionRoutes({store}: {store: SessionStore}) {
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot)
  useEffect(() => { void store.verify() }, [store])
  if (state.status === 'checking') return <div className="login-shell"><main className="login-layout"><section className="login-card" role="status" aria-live="polite"><h1>Verificando sessão…</h1><p className="card-description">Aguarde a confirmação do servidor.</p></section></main></div>
  if (state.status === 'error') return <div className="login-shell"><main className="login-layout"><section className="login-card"><h1>Não foi possível confirmar o acesso</h1><p className="feedback" role="alert">{state.message}</p><button type="button" className="submit-button" onClick={() => void store.verify()}>Consultar sessão novamente</button></section></main></div>
  const authenticated = state.status === 'authenticated'
  return <Routes>
    <Route path="/" element={authenticated ? <Navigate to="/painel" replace/> : <Login services={{login: store.login, getSession: store.confirmLogin}}/>}/>
    <Route path="/painel" element={authenticated ? <Panel state={state} store={store}/> : <Navigate to="/" replace/>}/>
    <Route path="/clientes" element={!authenticated ? <Navigate to="/" replace/> : state.session.permissions.includes('read_customers') ? <Customers session={state} store={store}/> : <div className="login-shell"><main className="login-layout"><section className="login-card"><h1>Acesso não autorizado</h1><p className="feedback" role="alert">Você não tem permissão para consultar os clientes.</p><Link to="/painel" className="back-link">Voltar ao painel</Link></section></main></div>}/>
    <Route path="/clientes/:customerId" element={!authenticated ? <Navigate to="/" replace/> : state.session.permissions.includes('read_customers') ? <CustomerDetail session={state} store={store}/> : <div className="login-shell"><main className="login-layout"><section className="login-card"><h1>Acesso não autorizado</h1><p className="feedback" role="alert">Você não tem permissão para consultar os clientes.</p><Link to="/painel" className="back-link">Voltar ao painel</Link></section></main></div>}/>
    <Route path="*" element={<Navigate to={authenticated ? '/painel' : '/'} replace/>}/>
  </Routes>
}

export default function App() {
  const [store] = useState(() => createSessionStore())
  return <BrowserRouter><SessionRoutes store={store}/></BrowserRouter>
}
