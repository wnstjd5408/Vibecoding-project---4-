import { useCallback, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { BottomSheet } from './BottomSheet.tsx'
import { SidePanel } from './SidePanel.tsx'
import { useWideLayout } from './useWideLayout.ts'

type ResponsiveSheetProps = {
  open: boolean
  onClose: () => void
  title: ReactNode
  badge?: ReactNode
  closeLabel?: string
  children: ReactNode
  // PC 폭에서 용어 링크가 aria-controls로 가리킬 패널 id
  panelId?: string
  // PC 패널을 닫을 때 포커스를 돌려줄 요소(예: 마지막으로 누른 용어 링크)
  returnFocus?: () => HTMLElement | null
  // false면 PC 폭에서도 바텀시트를 쓴다(PC 패널로 바꾸기로 한 안내만 true로 둔다)
  allowPanel?: boolean
}

// 폭에 따라 시트를 고른다. 1024px 이상이면 오른쪽 사이드 패널(SidePanel), 미만이면 기존 바텀시트(BottomSheet)다.
// 열림 상태는 부모가 계속 가지므로 창 크기를 바꿔도 열려 있던 것은 열린 채 모양만 바뀐다.
// 안쪽 내용(children)은 시트 종류가 바뀌어도 새로 만들어지지 않는다. 두 시트는 서로 다른 컴포넌트라 그냥 두면 내용이 다시 마운트되어
// 용어 설명(E06)·열람 기록(E07)·AI 설명(E09)을 다시 부르기 때문에(AI는 호출 한도와 비용이 걸려 있다), 내용을 따로 만든 요소(host)에
// 한 번만 그려 두고 지금 보이는 시트 안으로 옮겨 붙인다.
export function ResponsiveSheet({ panelId, returnFocus, allowPanel = true, children, ...sheet }: ResponsiveSheetProps) {
  const wide = useWideLayout()
  const [host] = useState(() => {
    const element = document.createElement('div')
    element.style.display = 'contents'
    return element
  })
  const attach = useCallback((slot: HTMLElement | null) => {
    if (slot !== null) slot.appendChild(host)
  }, [host])
  const slot = <div ref={attach} style={{ display: 'contents' }} />
  return (
    <>
      {wide && allowPanel ? <SidePanel id={panelId} returnFocus={returnFocus} {...sheet}>{slot}</SidePanel> : <BottomSheet {...sheet}>{slot}</BottomSheet>}
      {createPortal(children, host)}
    </>
  )
}
