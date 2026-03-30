import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from 'react-query'
import { DarkModeProvider } from './contexts/DarkModeContext'
import Layout from './components/Layout'
import Upload from './pages/Upload'
import Explore from './pages/Explore'
import HostDetail from './pages/HostDetail'
import Admin from './pages/Admin'

const queryClient = new QueryClient()

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <DarkModeProvider>
        <Router>
          <Layout>
            <Routes>
              <Route path="/" element={<Explore />} />
              <Route path="/upload" element={<Upload />} />
              <Route path="/host/:id" element={<HostDetail />} />
              <Route path="/admin" element={<Admin />} />
            </Routes>
          </Layout>
        </Router>
      </DarkModeProvider>
    </QueryClientProvider>
  )
}

export default App