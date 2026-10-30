import { useRoutes } from 'react-router'
import AccessNotice from './operator/AccessNotice.tsx'
import { appRoutes } from './routes/index.tsx'

function App() {
  const routes = useRoutes(appRoutes)
  return (
    <>
      {routes}
      <AccessNotice />
    </>
  )
}

export default App
