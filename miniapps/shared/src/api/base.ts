import type { MiniappIdentity } from '../types'

type QueryValue = string | number | boolean | undefined | null
type QueryParams = Record<string, QueryValue>

const MINIAPP_AUTH_TOKEN_KEY = 'miniapp_auth_token'
const MINIAPP_INIT_DATA_KEY = 'miniapp_init_data'
const TELEGRAM_INIT_DATA_WAIT_MS = 3000
const TELEGRAM_INIT_DATA_POLL_MS = 100
const AUTH_API_PREFIX = '/api/auth'
type AppBoundary = 'admin' | 'agents'

function resolveApiBaseUrl() {
  const configuredBaseUrl = import.meta.env.VITE_API_URL
  const normalizedConfiguredBaseUrl = configuredBaseUrl?.trim()
  const { protocol, hostname, port, origin, pathname } = window.location

  const isLocalhostConfig =
    normalizedConfiguredBaseUrl === 'http://localhost:8000' ||
    normalizedConfiguredBaseUrl === 'http://127.0.0.1:8000'
  const isServedFromBundledWebapp = pathname.startsWith('/webapp')

  if (normalizedConfiguredBaseUrl && !(protocol === 'https:' && isLocalhostConfig) && !isServedFromBundledWebapp) {
    return normalizedConfiguredBaseUrl
  }

  if (port === '5173' || port === '5175' || port === '5176' || port === '5177') {
    return `${protocol}//${hostname}:8000`
  }

  return origin
}

const apiBaseUrl = resolveApiBaseUrl()

function resolveAppBoundary(): AppBoundary | null {
  const configuredBoundary = String(import.meta.env.VITE_APP_BOUNDARY || '').trim().toLowerCase()
  if (configuredBoundary === 'admin' || configuredBoundary === 'agents') {
    return configuredBoundary
  }

  const { pathname, port } = window.location
  if (pathname.startsWith('/webapp/admin') || port === '5173') {
    return 'admin'
  }
  if (pathname.startsWith('/webapp/modbot') || port === '5177') {
    return 'admin'
  }
  if (pathname.startsWith('/webapp/agents') || pathname.startsWith('/webapp/agents-app') || port === '5175') {
    return 'agents'
  }
  return null
}

const appBoundary = resolveAppBoundary()

function withAppBoundary(headers: Record<string, string>) {
  if (appBoundary) {
    headers['X-App-Boundary'] = appBoundary
  }
  return headers
}

function readMiniappToken() {
  try {
    return window.sessionStorage.getItem(MINIAPP_AUTH_TOKEN_KEY)
  } catch {
    return null
  }
}

function writeMiniappToken(token: string | null) {
  try {
    if (token) {
      window.sessionStorage.setItem(MINIAPP_AUTH_TOKEN_KEY, token)
    } else {
      window.sessionStorage.removeItem(MINIAPP_AUTH_TOKEN_KEY)
    }
  } catch {
    // Ignore restrictive WebView storage failures.
  }
}

function readStoredInitData() {
  try {
    return window.sessionStorage.getItem(MINIAPP_INIT_DATA_KEY)
  } catch {
    return null
  }
}

function writeStoredInitData(initData: string | null) {
  try {
    if (initData) {
      window.sessionStorage.setItem(MINIAPP_INIT_DATA_KEY, initData)
    } else {
      window.sessionStorage.removeItem(MINIAPP_INIT_DATA_KEY)
    }
  } catch {
    // Ignore restrictive WebView storage failures.
  }
}

function readInitDataFromLocation() {
  const sources = [window.location.search, window.location.hash]

  for (const source of sources) {
    const value = source.startsWith('#') ? source.slice(1) : source
    const params = new URLSearchParams(value)
    const initData = params.get('tgWebAppData')?.trim() || params.get('init_data')?.trim() || params.get('initData')?.trim()
    if (initData) {
      return initData
    }
  }

  return null
}

function resolveAvailableInitData() {
  const telegramInitData = window.Telegram?.WebApp?.initData?.trim()
  if (telegramInitData) {
    writeStoredInitData(telegramInitData)
    return telegramInitData
  }

  const launchInitData = readInitDataFromLocation()
  if (launchInitData) {
    writeStoredInitData(launchInitData)
    return launchInitData
  }

  return readStoredInitData()
}

function buildUrl(path: string, params?: QueryParams) {
  const url = new URL(path, `${apiBaseUrl}/`)
  if (!params) {
    return url.toString()
  }

  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') {
      continue
    }
    url.searchParams.set(key, String(value))
  }

  return url.toString()
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function missingMiniappAuthError() {
  return new Error('Telegram authentication is unavailable. Open this WebApp from Telegram.')
}

async function waitForTelegramInitData(timeoutMs = TELEGRAM_INIT_DATA_WAIT_MS) {
  const deadline = Date.now() + timeoutMs

  while (Date.now() <= deadline) {
    const initData = resolveAvailableInitData()
    if (initData) {
      return initData
    }
    await sleep(TELEGRAM_INIT_DATA_POLL_MS)
  }

  return null
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.status === 401) {
    writeMiniappToken(null)
  }

  const text = await response.text()
  const payload = text ? JSON.parse(text) : null

  if (!response.ok) {
    const detail =
      payload && typeof payload === 'object' && 'detail' in payload && typeof payload.detail === 'string'
        ? payload.detail
        : `Request failed with status ${response.status}`
    throw new Error(detail)
  }

  return payload as T
}

let miniappTokenPromise: Promise<string | null> | null = null

async function ensureMiniappToken() {
  const cachedToken = readMiniappToken()
  if (cachedToken) {
    return cachedToken
  }

  if (miniappTokenPromise) {
    return miniappTokenPromise
  }

  const initData = await waitForTelegramInitData()
  if (!initData) {
    return null
  }

  miniappTokenPromise = fetch(buildUrl(`${AUTH_API_PREFIX}/miniapp/token`), {
    method: 'POST',
    headers: withAppBoundary({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ init_data: initData }),
  })
    .then((response) => parseResponse<{ token: string }>(response))
    .then((payload) => {
      writeMiniappToken(payload.token)
      return payload.token
    })
    .catch((_error) => {
      writeMiniappToken(null)
      return null
    })
    .finally(() => {
      miniappTokenPromise = null
    })

  return miniappTokenPromise
}

async function apiRequest<T>(
  path: string,
  options: {
    method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
    params?: QueryParams
    body?: unknown
  } = {},
) {
  async function buildHeaders(forceTokenRefresh = false) {
    if (forceTokenRefresh) {
      writeMiniappToken(null)
    }

    const token = await ensureMiniappToken()
    const headers: Record<string, string> = {}

    if (token) {
      headers.Authorization = `Bearer ${token}`
    } else {
      const initData = resolveAvailableInitData()
      if (initData) {
        headers['X-Telegram-Init-Data'] = initData
      } else {
        throw missingMiniappAuthError()
      }
    }

    if (options.body !== undefined) {
      headers['Content-Type'] = 'application/json'
    }

    return withAppBoundary(headers)
  }

  const requestUrl = buildUrl(path, options.params)
  const method = options.method || 'GET'
  const body = options.body !== undefined ? JSON.stringify(options.body) : undefined

  let response = await fetch(requestUrl, {
    method,
    headers: await buildHeaders(),
    body,
  })

  if (response.status === 401) {
    response = await fetch(requestUrl, {
      method,
      headers: await buildHeaders(true),
      body,
    })
  }

  return parseResponse<T>(response)
}

export const apiClient = {
  get: <T>(path: string, params?: QueryParams) => apiRequest<T>(path, { method: 'GET', params }),
  post: <T>(path: string, body?: unknown, params?: QueryParams) =>
    apiRequest<T>(path, { method: 'POST', body, params }),
  put: <T>(path: string, body?: unknown, params?: QueryParams) =>
    apiRequest<T>(path, { method: 'PUT', body, params }),
  patch: <T>(path: string, body?: unknown, params?: QueryParams) =>
    apiRequest<T>(path, { method: 'PATCH', body, params }),
  delete: <T>(path: string, params?: QueryParams) => apiRequest<T>(path, { method: 'DELETE', params }),
}

export async function fetchMe() {
  return apiClient.get<MiniappIdentity>(`${AUTH_API_PREFIX}/me`)
}

export async function updateLanguage(languageCode: string) {
  return apiClient.patch(`${AUTH_API_PREFIX}/language`, { language_code: languageCode })
}
