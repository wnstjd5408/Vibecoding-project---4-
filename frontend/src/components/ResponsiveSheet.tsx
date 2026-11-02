import { useCallback, useEffect, useRef, useState } from 'react'
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
  // 내용을 옮기면 안에 열려 있던 모달 dialog(예: 오류 신고 입력)가 DOM에서 빠졌다 들어오며 top layer에서 빠져, 열린 채 모달이 아니게 된다.
  // 그러면 Esc가 신고창이 아니라 바깥 패널까지 닫는다. 이전 시트는 새 시트가 자리 잡기 전에 이미 지워져 옮기기 전 상태는 읽을 수 없으므로,
  // BottomSheet가 늘 aria-modal로 표시하는 열린 dialog 중 모달이 아닌 것을 다시 모달로 연다.
  // 이펙트는 자식(시트)이 먼저 실행되므로 바깥 시트가 열린 뒤에 열어 안쪽 모달이 항상 위에 보인다.
  const focused = useRef<HTMLElement | null>(null)
  useEffect(() => {
    const track = (event: FocusEvent) => {
      focused.current = event.target instanceof HTMLElement ? event.target : null
    }
    // 포커스를 가진 요소가 DOM에서 빠질 때도 focusout(relatedTarget 없음)이 올 수 있어, 다른 곳으로 옮겨 간 것이 분명할 때만 잊는다.
    const release = (event: FocusEvent) => {
      if (event.relatedTarget instanceof Node && !host.contains(event.relatedTarget)) focused.current = null
    }
    host.addEventListener('focusin', track)
    host.addEventListener('focusout', release)
    return () => {
      host.removeEventListener('focusin', track)
      host.removeEventListener('focusout', release)
    }
  }, [host])
  useEffect(() => {
    // 다시 열 때 브라우저가 포커스를 옮기므로, 옮기기 전에 있던 요소를 먼저 기억해 두고 두 번의 확인에서 모두 쓴다.
    const before = focused.current
    const restore = () => {
      for (const dialog of host.querySelectorAll<HTMLDialogElement>('dialog[open][aria-modal="true"]')) {
        if (dialog.matches(':modal')) continue
        // close 이벤트는 비동기로 오고 그때는 이미 다시 열려 있어 BottomSheet가 부모에 닫힘을 알리지 않는다.
        dialog.close()
        dialog.showModal()
        if (before?.isConnected && dialog.contains(before)) before.focus({ preventScroll: true })
      }
    }
    restore()
    // 개발 모드의 StrictMode는 새로 만들어진 시트의 이펙트를 바로 이어서 한 번 더 실행해 바깥 시트를 닫았다 다시 연다. 그 뒤에도 한 번 더 확인한다.
    let cancelled = false
    queueMicrotask(() => {
      if (!cancelled) restore()
    })
    return () => {
      cancelled = true
    }
  }, [host, wide, allowPanel])
  const slot = <div ref={attach} style={{ display: 'contents' }} />
  return (
    <>
      {wide && allowPanel ? <SidePanel id={panelId} returnFocus={returnFocus} {...sheet}>{slot}</SidePanel> : <BottomSheet {...sheet}>{slot}</BottomSheet>}
      {createPortal(children, host)}
    </>
  )
}
