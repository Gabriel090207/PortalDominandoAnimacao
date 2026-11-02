import {FiRefreshCw} from 'react-icons/fi'
import '../SessionVerificationError/SessionVerificationError.css'

/** Presentation for real pending work; owns no requests, timers or session state. */
export default function AdminLoading({message='Verificando sessão…'}:{message?:string}){
  return <main className="session-verification-error" aria-labelledby="admin-loading-title" aria-busy="true">
    <div className="session-verification-error__background" aria-hidden="true"><span className="session-verification-error__glow"/><span className="session-verification-error__grid"/></div>
    <div className="session-verification-error__content">
      <header className="session-verification-error__brand"><span>Dominando <strong>Animação</strong></span><p>Área administrativa</p></header>
      <section className="session-verification-error__card" role="status" aria-live="polite">
        <div className="session-verification-error__symbol" aria-hidden="true"><FiRefreshCw/></div>
        <h1 id="admin-loading-title">Preparando seu painel…</h1>
        <p className="session-verification-error__message">{message}</p>
      </section>
    </div>
  </main>
}
