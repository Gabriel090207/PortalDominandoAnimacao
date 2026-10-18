import { useRef, useState } from 'react'
import { FiArrowRight, FiCheck, FiEye, FiEyeOff, FiLock, FiMail } from 'react-icons/fi'
import type { FormEvent } from 'react'
import { getAdminSession, loginAdmin } from '../../services/adminApi'
import { createLoginController } from './loginController'
import type { LoginState, LoginServices } from './loginController'
import './Login.css'

const defaultServices: LoginServices = { login: loginAdmin, getSession: getAdminSession }

export default function Login({services = defaultServices}: {services?: LoginServices}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [visible, setVisible] = useState(false)
  const [state, setState] = useState<LoginState>({ phase: 'idle' })
  const controller = useRef<ReturnType<typeof createLoginController> | null>(null)
  if (!controller.current) controller.current = createLoginController(services, setState)
  const pending = state.phase === 'submitting' || state.phase === 'checking'
  const confirmed = state.phase === 'authenticated'
  const unconfirmed = state.phase === 'unconfirmed'

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const credentials = { email, password }
    setPassword('')
    setVisible(false)
    await controller.current!.submit(credentials)
  }

  return <div className="login-shell">
    <main className="login-layout">
      <section className="login-card" aria-labelledby="login-title" aria-busy={pending}>
        <header className="brand"><span className="brand-name">Dominando<span>Animação</span></span></header>
        <p className="card-eyebrow">ACESSO ADMINISTRATIVO</p>
        <h1 id="login-title">{confirmed ? 'Acesso confirmado' : unconfirmed ? 'Confirme sua sessão' : 'Bem-vindo de volta'}</h1>
        <p className="card-description">{confirmed ? 'Sua sessão foi validada pelo servidor.' : unconfirmed ? 'Não é necessário enviar sua senha novamente.' : 'Entre com seu e-mail e senha para continuar.'}</p>
        <div className="feedback-region" aria-live="polite" aria-atomic="true">
          {state.message && <p id="login-feedback" className={`feedback ${unconfirmed ? 'feedback-notice' : ''}`} role="alert">{state.message}</p>}
          {pending && <span className="sr-only">{state.phase === 'checking' ? 'Confirmando sua sessão.' : 'Verificando suas credenciais.'}</span>}
        </div>
        {confirmed ? <div className="success-panel" role="status"><FiCheck className="success-check" aria-hidden="true"/><p>Sessão administrativa confirmada.</p><p className="success-email">{state.session?.email}</p><p>O painel será disponibilizado em uma próxima etapa.</p></div>
          : unconfirmed ? <button className="submit-button" type="button" onClick={() => void controller.current!.retrySession()}>Consultar sessão novamente <FiArrowRight aria-hidden="true"/></button>
          : <form onSubmit={submit} noValidate>
            <div className="field"><label htmlFor="admin-email">E-mail administrativo</label><div className="input-wrap"><FiMail className="input-icon" aria-hidden="true"/><input id="admin-email" name="email" type="email" inputMode="email" autoComplete="username" autoCapitalize="none" spellCheck={false} value={email} onChange={event => setEmail(event.target.value)} disabled={pending} aria-describedby={state.message ? 'login-feedback' : 'login-help'} placeholder="Seu e-mail"/></div></div>
            <div className="field"><label htmlFor="admin-password">Senha</label><div className="input-wrap password-field"><FiLock className="input-icon" aria-hidden="true"/><input id="admin-password" name="password" type={visible ? 'text' : 'password'} autoComplete="current-password" aria-describedby={state.message ? 'login-feedback' : undefined} value={password} onChange={event => setPassword(event.target.value)} disabled={pending} placeholder="Sua senha"/><button type="button" className="visibility-button" onClick={() => setVisible(value => !value)} disabled={pending} aria-label={visible ? 'Ocultar senha' : 'Mostrar senha'} aria-pressed={visible} aria-controls="admin-password">{visible ? <FiEyeOff aria-hidden="true"/> : <FiEye aria-hidden="true"/>}</button></div></div>
            <button className="submit-button" type="submit" disabled={pending}>{pending ? <><span className="spinner" aria-hidden="true"/>{state.phase === 'checking' ? 'Confirmando sessão…' : 'Entrando…'}</> : <>Entrar no Admin <FiArrowRight aria-hidden="true"/></>}</button>
            <p id="login-help" className="form-help">Use somente as credenciais fornecidas para administrar o portal.</p>
          </form>}
        <div className="card-footer"><FiLock aria-hidden="true"/><span>Sua senha não é armazenada neste navegador.</span></div>
      </section>
    </main>
  </div>
}
