import { useNavigate, useSearchParams } from 'react-router'
import { previewPath } from './screens.ts'
import type { ScreenId } from './screens.ts'

export function useGo() {
  const navigate = useNavigate()
  const [query] = useSearchParams()
  return (id: ScreenId) => {
    const suffix = query.toString()
    navigate(`${previewPath(id)}${suffix ? `?${suffix}` : ''}`)
  }
}
