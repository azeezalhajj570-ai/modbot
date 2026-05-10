import axios from 'axios'
import { login, fetchCurrentUser } from '../lib/api'

vi.mock('axios', () => {
  const mockAxiosInstance = {
    post: vi.fn(),
    get: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  }

  return {
    default: {
      create: vi.fn(() => mockAxiosInstance),
    },
  }
})

const mockAxiosInstance = axios.create()

beforeEach(() => {
  vi.clearAllMocks()
})

describe('login', () => {
  it('calls POST /auth/email/login with email and password', async () => {
    const expectedData = { token: 'test-token' }
    ;(mockAxiosInstance.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: expectedData })

    const result = await login('user@example.com', 'secret123')

    expect(mockAxiosInstance.post).toHaveBeenCalledWith('/auth/email/login', {
      email: 'user@example.com',
      password: 'secret123',
    })
    expect(result).toEqual(expectedData)
  })
})

describe('fetchCurrentUser', () => {
  it('calls GET /api/auth/me with Bearer token', async () => {
    const expectedData = { user: { id: 1, username: 'admin' }, is_bot_owner: false }
    ;(mockAxiosInstance.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: expectedData })

    const result = await fetchCurrentUser('my-jwt-token')

    expect(mockAxiosInstance.get).toHaveBeenCalledWith('/api/auth/me', {
      headers: { Authorization: 'Bearer my-jwt-token' },
    })
    expect(result).toEqual(expectedData)
  })

  it('calls GET /api/auth/me without Authorization header when no token', async () => {
    const expectedData = { user: { id: 1, username: 'admin' }, is_bot_owner: false }
    ;(mockAxiosInstance.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: expectedData })

    const result = await fetchCurrentUser()

    expect(mockAxiosInstance.get).toHaveBeenCalledWith('/api/auth/me', {
      headers: undefined,
    })
    expect(result).toEqual(expectedData)
  })
})
