import { Navigate, Route, Routes } from 'react-router-dom'
import InboxScrollMemory from './components/InboxScrollMemory'
import Shell from './components/Shell'
import AccountsPage from './pages/AccountsPage'
import DashboardPage from './pages/DashboardPage'
import GroupsPage from './pages/GroupsPage'
import InboxPage from './pages/InboxPage'
import LogsPage from './pages/LogsPage'
import ResultsPage from './pages/ResultsPage'
import SettingsPage from './pages/SettingsPage'

export default function App() {
  return <Shell><Routes>
    <Route path="/" element={<DashboardPage />} />
    <Route path="/groups" element={<GroupsPage />} />
    <Route path="/inbox" element={<InboxScrollMemory><InboxPage /></InboxScrollMemory>} />
    <Route path="/success" element={<ResultsPage key="success" kind="success" />} />
    <Route path="/failed" element={<ResultsPage key="failed" kind="failed" />} />
    <Route path="/accounts" element={<AccountsPage />} />
    <Route path="/logs" element={<LogsPage />} />
    <Route path="/settings" element={<SettingsPage />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes></Shell>
}
