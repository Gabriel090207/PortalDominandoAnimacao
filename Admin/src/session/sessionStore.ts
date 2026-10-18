import { AdminApiError, getAdminSession, loginAdmin, logoutAdmin } from '../services/adminApi.ts'
import type { AdminSession, LoginCredentials, LoginResult, LogoutResult } from '../services/adminApi.ts'

export interface SessionServices {
  login(credentials: LoginCredentials): Promise<LoginResult>
  getSession(): Promise<AdminSession>
  logout(): Promise<LogoutResult>
}
export type SessionState =
  | { status: 'checking' | 'unauthenticated' | 'error'; message?: string }
  | { status: 'authenticated'; session: AdminSession; loggingOut: boolean; message?: string }
const unavailable = 'Não foi possível confirmar a sessão. Isso não significa que ela expirou ou que houve logout. Tente consultar novamente.'
const isUnauthorized = (error: unknown) => error instanceof AdminApiError && error.status === 401

export function createSessionStore(services: SessionServices = {
  login: loginAdmin, getSession: getAdminSession, logout: logoutAdmin,
}) {
  let state: SessionState = { status: 'checking' }
  const listeners = new Set<() => void>()
  let version = 0
  let verification: { version: number; promise: Promise<void> } | undefined
  let loginBusy = false
  let loginVersion: number | undefined
  let logoutPromise: Promise<void> | undefined
  function publish(next: SessionState) { state = next; listeners.forEach(listener => listener()) }
  function invalidate() { version++; loginVersion = undefined; publish({ status: 'unauthenticated' }) }
  function stale() { return new AdminApiError('invalid_session', 401) }

  return {
    getSnapshot: () => state,
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener) } },
    verify(): Promise<void> {
      if (logoutPromise) return logoutPromise
      if (verification?.version === version) return verification.promise
      const current = ++version
      loginVersion = undefined
      publish({ status: 'checking' })
      const promise = (async () => {
        try {
          const session = await Promise.resolve().then(() => services.getSession())
          if (current === version) publish({ status: 'authenticated', session, loggingOut: false })
        } catch (error) {
          if (current === version) publish(isUnauthorized(error) ? { status: 'unauthenticated' } : { status: 'error', message: unavailable })
        } finally { if (verification?.version === current) verification = undefined }
      })()
      verification = { version: current, promise }
      return promise
    },
    async login(credentials: LoginCredentials): Promise<LoginResult> {
      if (loginBusy || logoutPromise) throw new AdminApiError('unavailable', 503)
      loginBusy = true
      const current = ++version
      loginVersion = current
      try {
        const result = await services.login(credentials)
        if (current !== version) throw stale()
        return result
      } finally { loginBusy = false }
    },
    async confirmLogin(): Promise<AdminSession> {
      if (loginVersion === undefined || loginVersion !== version || logoutPromise) throw stale()
      const current = ++version
      loginVersion = current
      try {
        const session = await services.getSession()
        if (current !== version) throw stale()
        publish({ status: 'authenticated', session, loggingOut: false })
        return session
      } catch (error) {
        if (current === version) publish(isUnauthorized(error) ? { status: 'unauthenticated' } : { status: 'error', message: unavailable })
        throw error
      }
    },
    logout(): Promise<void> {
      if (logoutPromise) return logoutPromise
      const current = ++version
      loginVersion = undefined
      const before = state
      if (before.status === 'authenticated') publish({ ...before, loggingOut: true, message: undefined })
      const promise = (async () => {
        try {
          await Promise.resolve().then(() => services.logout())
          if (current === version) publish({ status: 'unauthenticated' })
        } catch (error) {
          if (current === version) {
            if (isUnauthorized(error)) publish({ status: 'unauthenticated' })
            else if (before.status === 'authenticated') publish({ ...before, loggingOut: false, message: 'Não foi possível confirmar o encerramento da sessão. Tente sair novamente.' })
            else publish({ status: 'error', message: unavailable })
          }
        } finally { logoutPromise = undefined }
      })()
      logoutPromise = promise
      return promise
    },
    handleUnauthorized(error: unknown) {
      if (isUnauthorized(error)) invalidate()
    },
  }
}
export type SessionStore = ReturnType<typeof createSessionStore>
