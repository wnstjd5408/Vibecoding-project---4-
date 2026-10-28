import { useRoutes } from 'react-router'
import { appRoutes } from './routes/index.tsx'

function App() {
  return useRoutes(appRoutes)
}

export default App
