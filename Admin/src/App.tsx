import { useEffect, useState, useSyncExternalStore } from 'react'
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom'
import Login from './pages/Login/Login'
import AdminLoading from './components/AdminLoading/AdminLoading'
import Customers from './pages/Customers/Customers'
import CustomerDetail from './pages/Customers/CustomerDetail'
import SessionVerificationError from './components/SessionVerificationError/SessionVerificationError'
import { createSessionStore } from './session/sessionStore'
import type { SessionStore } from './session/sessionStore'

export function SessionRoutes({store}: {store: SessionStore}) {
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot)
  useEffect(() => { void store.verify() }, [store])
  if (state.status === 'checking') return <AdminLoading/>
  if (state.status === 'error') return <SessionVerificationError message={state.message}><button type="button" onClick={() => void store.verify()}>Consultar sessão novamente</button></SessionVerificationError>
  const authenticated = state.status === 'authenticated'
  return <Routes>
    <Route path="/" element={authenticated ? <Navigate to="/clientes" replace/> : <Login services={{login: store.login, getSession: store.confirmLogin}}/>}/>
    <Route path="/painel" element={authenticated ? <Navigate to="/clientes" replace/> : <Navigate to="/" replace/>}/>
    <Route path="/clientes" element={!authenticated ? <Navigate to="/" replace/> : state.session.permissions.includes('read_customers') ? <Customers session={state} store={store}/> : <div className="login-shell"><main className="login-layout"><section className="login-card"><h1>Acesso não autorizado</h1><p className="feedback" role="alert">Você não tem permissão para consultar os clientes.</p><Link to="/clientes" className="back-link">Voltar aos clientes</Link></section></main></div>}/>
    <Route path="/clientes/:customerId" element={!authenticated ? <Navigate to="/" replace/> : state.session.permissions.includes('read_customers') ? <CustomerDetail session={state} store={store}/> : <div className="login-shell"><main className="login-layout"><section className="login-card"><h1>Acesso não autorizado</h1><p className="feedback" role="alert">Você não tem permissão para consultar os clientes.</p><Link to="/clientes" className="back-link">Voltar aos clientes</Link></section></main></div>}/>
    <Route path="*" element={<Navigate to={authenticated ? '/clientes' : '/'} replace/>}/>
  </Routes>
}

export default function App() {
  const [store] = useState(() => createSessionStore())
  return <BrowserRouter><SessionRoutes store={store}/></BrowserRouter>
}
