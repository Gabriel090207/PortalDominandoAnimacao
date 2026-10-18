import axios from 'axios'
import type { AxiosAdapter } from 'axios'

export type AdminRole = 'owner' | 'operator'
export type AdminPermission =
  | 'read_customers' | 'read_dashboard' | 'read_audit' | 'activate_customer'
  | 'suspend_customer' | 'resume_customer' | 'block_customer' | 'unblock_customer'
export interface LoginCredentials { email: string; password: string }
export interface LoginResult { admin_id: string }
export interface AdminSession {
  admin_id: string
  email: string
  role: AdminRole
  permissions: AdminPermission[]
}
export interface LogoutResult { success: true }
export type CustomerAccountStatus = 'enabled' | 'blocked'
export type CustomerActivationStatus = 'pending' | 'active' | 'suspended'
export interface AdminCustomer {
  customer_id: string
  email: string
  account_status: CustomerAccountStatus
  activation_status: CustomerActivationStatus
  created_at: string
}
export interface AdminCustomerPage { items: AdminCustomer[]; next_cursor: string | null }
export interface AdminPurchaseConfirmation {
  customer_id:string
  approved_purchase_recorded:boolean
  current_payment_validity:'not_verified'
  requires_kirvano_review:true
}
export interface CustomerActivationResult {
  customer_id:string
  activation_status:'active'
  result:'activated'|'already_active'
}
export interface CustomerSuspensionResult {
  customer_id:string
  activation_status:'suspended'
  result:'suspended'|'already_suspended'
}
export interface CustomerResumptionResult {
  customer_id:string
  activation_status:'active'
  result:'resumed'|'already_active'
}
export interface CustomerQuery { limit?: number; cursor?: string }

// One URL segment, with the same document-ID constraints as the backend.
export function customerPath(customerId: string): string {
  if (typeof customerId !== 'string' || !customerId || customerId.includes('/') ||
    customerId === '.' || customerId === '..' || /^__.*__$/.test(customerId) ||
    /[\p{Cc}\p{Cs}]/u.test(customerId) || new TextEncoder().encode(customerId).length > 1500)
    throw new AdminApiError('invalid_request', 400)
  return `/admin/customers/${encodeURIComponent(customerId)}`
}

function projectCustomer(item: AdminCustomer): AdminCustomer {
  if (!item || typeof item.customer_id !== 'string' || !item.customer_id || typeof item.email !== 'string' ||
    typeof item.account_status !== 'string' || typeof item.activation_status !== 'string') throw new AdminApiError('unexpected_response')
  return {customer_id:item.customer_id,email:item.email,account_status:item.account_status,
    activation_status:item.activation_status,created_at:typeof item.created_at === 'string' ? item.created_at : ''}
}

export type AdminApiErrorKind = 'configuration' | 'invalid_credentials' | 'invalid_session'
  | 'forbidden' | 'rate_limited' | 'unavailable' | 'network' | 'invalid_request'
  | 'request_too_large' | 'unsupported_media_type' | 'unexpected_response'

const messages: Record<AdminApiErrorKind, string> = {
  configuration: 'API administrativa não configurada corretamente.',
  invalid_credentials: 'Credenciais administrativas inválidas.',
  invalid_session: 'Sessão administrativa ausente ou inválida.',
  forbidden: 'Requisição administrativa não autorizada.',
  rate_limited: 'Limite de tentativas atingido.',
  unavailable: 'Serviço administrativo indisponível.',
  network: 'Não foi possível confirmar a comunicação com o servidor.',
  invalid_request: 'Requisição administrativa inválida.',
  request_too_large: 'Requisição administrativa excede o tamanho permitido.',
  unsupported_media_type: 'Formato de requisição não permitido.',
  unexpected_response: 'Resposta administrativa inesperada.',
}

export class AdminApiError extends Error {
  readonly kind: AdminApiErrorKind
  readonly status: number | undefined
  readonly retryAfter: string | undefined
  constructor(kind: AdminApiErrorKind, status?: number, retryAfter?: string) {
    super(messages[kind])
    this.name = 'AdminApiError'
    this.kind = kind
    this.status = status
    this.retryAfter = retryAfter
  }
}

function normalizeFailure(error: unknown, operation: 'login' | 'session' | 'logout' | 'customers'): AdminApiError {
  if (!axios.isAxiosError(error)) return new AdminApiError('unexpected_response')
  if (!error.response) return new AdminApiError('network')
  const status = error.response.status
  const raw = error.response.headers['retry-after']
  // Current backend contract is an integer number of seconds. Preserve exactly;
  // never invent a timeout, keep the raw Axios error or echo server response data.
  const retryAfter = typeof raw === 'string' && /^\d{1,20}$/.test(raw) ? raw : undefined
  const kind: AdminApiErrorKind = status === 401 ? (operation === 'login' ? 'invalid_credentials' : 'invalid_session')
    : status === 403 ? 'forbidden' : status === 429 ? 'rate_limited'
    : status >= 500 ? 'unavailable' : status === 413 ? 'request_too_large'
    : status === 415 ? 'unsupported_media_type' : status === 400 || status === 422 ? 'invalid_request'
    : 'unexpected_response'
  return new AdminApiError(kind, status, retryAfter)
}

export function createAdminApi(apiURL: string, adapter?: AxiosAdapter) {
  let baseURL: string
  try {
    const url = new URL(apiURL)
    if (apiURL !== apiURL.trim() || url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) throw new Error()
    baseURL = url.href.replace(/\/$/, '')
  } catch { throw new AdminApiError('configuration') }
  const http = axios.create({ baseURL, withCredentials: true, ...(adapter ? { adapter } : {}) })
  async function request<T>(operation: 'login' | 'session' | 'logout' | 'customers', perform: () => Promise<{ data: T }>): Promise<T> {
    try { return (await perform()).data } catch (error) { throw normalizeFailure(error, operation) }
  }
  return {
    async login(credentials: LoginCredentials): Promise<LoginResult> {
      const data = await request('login', () => http.post<LoginResult>('/admin/auth/login',
        { email: credentials.email, password: credentials.password },
        { headers: { 'Content-Type': 'application/json', 'X-Admin-Request': '1' } }))
      if (!data || typeof data.admin_id !== 'string' || !data.admin_id) throw new AdminApiError('unexpected_response')
      return { admin_id: data.admin_id }
    },
    async getSession(): Promise<AdminSession> {
      const data = await request('session', () => http.get<AdminSession>('/admin/auth/session'))
      const permissions: AdminPermission[] = ['read_customers', 'read_dashboard', 'read_audit', 'activate_customer',
        'suspend_customer', 'resume_customer', 'block_customer', 'unblock_customer']
      if (!data || typeof data.admin_id !== 'string' || !data.admin_id || typeof data.email !== 'string'
        || !['owner', 'operator'].includes(data.role) || !Array.isArray(data.permissions)
        || !data.permissions.every(permission => permissions.includes(permission))) throw new AdminApiError('unexpected_response')
      return { admin_id: data.admin_id, email: data.email, role: data.role, permissions: [...data.permissions] }
    },
    async getCustomers({limit = 20, cursor}: CustomerQuery = {}): Promise<AdminCustomerPage> {
      if (!Number.isInteger(limit) || limit < 1 || limit > 50 ||
        (cursor !== undefined && !/^[A-Za-z0-9_-]{1,2000}$/.test(cursor))) throw new AdminApiError('invalid_request')
      const data = await request('customers', () => http.get<AdminCustomerPage>('/admin/customers',
        { params: { limit, ...(cursor === undefined ? {} : {cursor}) } }))
      if (!data || !Array.isArray(data.items) || data.items.length > limit ||
        !(data.next_cursor === null || (typeof data.next_cursor === 'string' && /^[A-Za-z0-9_-]{1,2000}$/.test(data.next_cursor)))) throw new AdminApiError('unexpected_response')
      const items = data.items.map(projectCustomer)
      return {items, next_cursor: data.next_cursor}
    },
    async activateCustomer(customerId: string): Promise<CustomerActivationResult> {
      const path = `${customerPath(customerId)}/activate`
      const data = await request('customers', () => http.post<CustomerActivationResult>(path,
        {confirm_activation:true}, {headers: {'Content-Type':'application/json','X-Admin-Request':'1'}}))
      if (!data || data.customer_id !== customerId || data.activation_status !== 'active'
        || !['activated','already_active'].includes(data.result)) throw new AdminApiError('unexpected_response')
      return {customer_id:data.customer_id,activation_status:'active',result:data.result}
    },
    async suspendCustomer(customerId: string): Promise<CustomerSuspensionResult> {
      const path = `${customerPath(customerId)}/suspend`
      const data = await request('customers', () => http.post<CustomerSuspensionResult>(path,
        {confirm_suspension:true}, {headers: {'Content-Type':'application/json','X-Admin-Request':'1'}}))
      if (!data || data.customer_id !== customerId || data.activation_status !== 'suspended'
        || !['suspended','already_suspended'].includes(data.result)) throw new AdminApiError('unexpected_response')
      return {customer_id:data.customer_id,activation_status:'suspended',result:data.result}
    },
    async resumeCustomer(customerId: string): Promise<CustomerResumptionResult> {
      const path = `${customerPath(customerId)}/resume`
      const data = await request('customers', () => http.post<CustomerResumptionResult>(path,
        {confirm_resumption:true}, {headers: {'Content-Type':'application/json','X-Admin-Request':'1'}}))
      if (!data || data.customer_id !== customerId || data.activation_status !== 'active'
        || !['resumed','already_active'].includes(data.result)) throw new AdminApiError('unexpected_response')
      return {customer_id:data.customer_id,activation_status:'active',result:data.result}
    },
    async getPurchaseConfirmation(customerId: string): Promise<AdminPurchaseConfirmation> {
      const path = `${customerPath(customerId)}/purchase-confirmation`
      const data = await request('customers', () => http.get<AdminPurchaseConfirmation>(path))
      if (!data || data.customer_id !== customerId || typeof data.approved_purchase_recorded !== 'boolean'
        || data.current_payment_validity !== 'not_verified' || data.requires_kirvano_review !== true)
        throw new AdminApiError('unexpected_response')
      return {customer_id:data.customer_id,approved_purchase_recorded:data.approved_purchase_recorded,
        current_payment_validity:data.current_payment_validity,requires_kirvano_review:data.requires_kirvano_review}
    },
    async lookupCustomer(email: string): Promise<AdminCustomer> {
      const data = await request('customers', () => http.post<AdminCustomer>('/admin/customers/lookup',
        {email}, {headers: {'Content-Type':'application/json', 'X-Admin-Request':'1'}}))
      const customer = projectCustomer(data)
      customerPath(customer.customer_id)
      return customer
    },
    async getCustomer(customerId: string): Promise<AdminCustomer> {
      const path = customerPath(customerId)
      const data = await request('customers', () => http.get<AdminCustomer>(path))
      const customer = projectCustomer(data)
      if (customer.customer_id !== customerId) throw new AdminApiError('unexpected_response')
      return customer
    },
    async logout(): Promise<LogoutResult> {
      const data = await request('logout', () => http.post<LogoutResult>('/admin/auth/logout', undefined,
        { headers: { 'X-Admin-Request': '1' } }))
      if (!data || data.success !== true) throw new AdminApiError('unexpected_response')
      return { success: true }
    },
  }
}

let browserApi: ReturnType<typeof createAdminApi> | undefined
function configuredApi() {
  // No client or HTTP request is created until explicitly invoked by future UI.
  browserApi ??= createAdminApi(import.meta.env.VITE_API_URL ?? '')
  return browserApi
}
export const loginAdmin = (credentials: LoginCredentials) => configuredApi().login(credentials)
export const getAdminSession = () => configuredApi().getSession()
export const logoutAdmin = () => configuredApi().logout()

export const getAdminCustomers = (query?: CustomerQuery) => configuredApi().getCustomers(query)

export const getAdminCustomer = (customerId: string) => configuredApi().getCustomer(customerId)

export const lookupAdminCustomer = (email: string) => configuredApi().lookupCustomer(email)

export const getAdminPurchaseConfirmation = (customerId: string) => configuredApi().getPurchaseConfirmation(customerId)

export const activateAdminCustomer = (customerId: string) => configuredApi().activateCustomer(customerId)

export const suspendAdminCustomer = (customerId: string) => configuredApi().suspendCustomer(customerId)

export const resumeAdminCustomer = (customerId: string) => configuredApi().resumeCustomer(customerId)
