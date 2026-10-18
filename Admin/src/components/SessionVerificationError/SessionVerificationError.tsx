import {FiRefreshCw,FiInfo} from 'react-icons/fi'
import type {ReactNode} from 'react'
import './SessionVerificationError.css'

/** Presentation only; verification state and the retry handler belong to SessionRoutes. */
export default function SessionVerificationError({message,children}:{message?:string;children:ReactNode}){
  return <main className="session-verification-error" aria-labelledby="session-verification-title">
    <div className="session-verification-error__background" aria-hidden="true">
      <span className="session-verification-error__glow"/>
      <span className="session-verification-error__grid"/>
    </div>
    <div className="session-verification-error__content">
      <header className="session-verification-error__brand"><span>Dominando <strong>Animação</strong></span><p>Área administrativa</p></header>
      <section className="session-verification-error__card" aria-labelledby="session-verification-title">
        <div className="session-verification-error__symbol" aria-hidden="true"><FiRefreshCw/></div>
        <p className="session-verification-error__eyebrow">Verificação de sessão</p>
        <h1 id="session-verification-title">Não foi possível confirmar o acesso</h1>
        <p className="session-verification-error__message" role="alert">{message}</p>
        <div className="session-verification-error__retry">{children}</div>
        <p className="session-verification-error__note"><FiInfo aria-hidden="true"/>As páginas protegidas permanecem indisponíveis até a confirmação.</p>
      </section>
      <footer className="session-verification-error__footer">Dominando Animação <span aria-hidden="true">·</span> Acesso administrativo</footer>
    </div>
  </main>
}
