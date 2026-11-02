import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import './styles/tokens.css'
import './styles/global.css'
import App from './App.tsx'
import { AuthProvider } from './auth/AuthProvider.tsx'
import { LoginPromptProvider } from './loginPrompt/LoginPromptProvider.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <LoginPromptProvider>
          <App />
        </LoginPromptProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
