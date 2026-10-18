import { AdminApiError } from '../../services/adminApi.ts'
import type { AdminSession, LoginCredentials, LoginResult } from '../../services/adminApi.ts'

export type LoginPhase = 'idle' | 'submitting' | 'checking' | 'error' | 'unconfirmed' | 'authenticated'
export interface LoginState { phase: LoginPhase; message?: string; session?: AdminSession }
export interface LoginServices {
  login(credentials: LoginCredentials): Promise<LoginResult>
  getSession(): Promise<AdminSession>
}

function safeMessage(error: unknown) {
  if (!(error instanceof AdminApiError)) return 'Não foi possível concluir a solicitação. Tente novamente mais tarde.'
  if (error.kind === 'configuration') return 'O acesso administrativo ainda não está disponível neste ambiente.'
  if (error.kind === 'rate_limited' && error.retryAfter) {
    return `${error.message} Aguarde ${error.retryAfter} segundos antes de tentar novamente.`
  }
  return error.message
}

export function createLoginController(services: LoginServices, publish: (state: LoginState) => void) {
  let busy = false
  let phase: LoginPhase = 'idle'
  function update(state: LoginState) { phase = state.phase; publish(state) }
  async function confirm() {
    update({ phase: 'checking' })
    try {
      const session = await services.getSession()
      update({ phase: 'authenticated', session })
    } catch {
      update({ phase: 'unconfirmed', message: 'O login foi recebido, mas não foi possível confirmar a sessão. Isso não significa que ela foi encerrada. Você pode consultar novamente.' })
    }
  }
  return {
    async submit(credentials: LoginCredentials) {
      if (busy || phase === 'authenticated' || phase === 'unconfirmed') return
      busy = true
      update({ phase: 'submitting' })
      try {
        await services.login(credentials)
        await confirm()
      } catch (error) {
        update({ phase: 'error', message: safeMessage(error) })
      } finally { busy = false }
    },
    async retrySession() {
      if (busy || phase !== 'unconfirmed') return
      busy = true
      try { await confirm() } finally { busy = false }
    },
  }
}
