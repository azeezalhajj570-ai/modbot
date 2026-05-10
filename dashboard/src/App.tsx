import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import Layout from './components/Layout'
import ActivityPage from './pages/ActivityPage'
import AutomationPage from './pages/AutomationPage'
import DashboardPage from './pages/DashboardPage'
import FAQPage from './pages/FAQPage'
import LoginPage from './pages/LoginPage'
import MembersPage from './pages/MembersPage'
import OwnerPage from './pages/OwnerPage'
import RulesPage from './pages/RulesPage'
import SettingsPage from './pages/SettingsPage'
import SummariesPage from './pages/SummariesPage'
import SubscriptionsPage from './pages/SubscriptionsPage'

const queryClient = new QueryClient()

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename="/dashboard">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<Layout />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/members" element={<MembersPage />} />
            <Route path="/rules" element={<RulesPage />} />
            <Route path="/activity" element={<ActivityPage />} />
            <Route path="/automation" element={<AutomationPage />} />
            <Route path="/subscriptions" element={<SubscriptionsPage />} />
            <Route path="/owner" element={<OwnerPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/faq" element={<FAQPage />} />
            <Route path="/summaries" element={<SummariesPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
