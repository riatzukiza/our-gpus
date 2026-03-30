import React from 'react'
import ReactDOM from 'react-dom/client'
import axios from 'axios'
import App from './App'
import './index.css'
import { getStoredAdminApiKey } from './lib/adminAuth'

axios.interceptors.request.use((config) => {
  const apiKey = getStoredAdminApiKey()
  if (apiKey) {
    config.headers = config.headers || {}
    config.headers['X-API-Key'] = apiKey
  }
  return config
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
