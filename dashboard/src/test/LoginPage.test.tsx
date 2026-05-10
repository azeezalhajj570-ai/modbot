import { render, screen } from '@testing-library/react'
import LoginPage from '../pages/LoginPage'

vi.mock('react-router-dom', () => ({
  useNavigate: vi.fn(),
}))

vi.mock('../lib/auth', () => ({
  storeAuth: vi.fn(),
}))

vi.mock('../lib/api', () => ({
  login: vi.fn(),
  fetchCurrentUser: vi.fn(),
  telegramLogin: vi.fn(),
}))

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network error'))
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('LoginPage', () => {
  it('renders the login form with email input', async () => {
    render(<LoginPage />)
    expect(await screen.findByPlaceholderText('Email')).toBeInTheDocument()
  })

  it('renders the login form with password input', async () => {
    render(<LoginPage />)
    expect(await screen.findByPlaceholderText('Password')).toBeInTheDocument()
  })

  it('renders a sign in button', async () => {
    render(<LoginPage />)
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  })
})
