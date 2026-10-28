import { useState } from 'react'
import type { ReactNode } from 'react'
import { initialAdminNotes, initialNotes, initialReports, initialTerms } from './data.ts'
import { PreviewContext } from './model.ts'
import type { PreviewModel } from './model.ts'

export function PreviewProvider({ children }: { children: ReactNode }) {
  const [notes, setNotes] = useState(initialNotes)
  const [adminNotes, setAdminNotes] = useState(initialAdminNotes)
  const [terms, setTerms] = useState(initialTerms)
  const [reports, setReports] = useState(initialReports)
  const [noteId, setNoteId] = useState(11)
  const [termId, setTermId] = useState(7)
  const [reportId, setReportId] = useState(1)
  const [answer, setAnswer] = useState('')
  const [favorites, setFavorites] = useState<number[]>([])
  const [issued, setIssued] = useState({ email: 'member@example.test', name: '합성 사용자' })
  const [role, setRole] = useState<PreviewModel['role']>('visitor')
  const [notice, setNotice] = useState('')
  return <PreviewContext value={{ notes, setNotes, adminNotes, setAdminNotes, terms, setTerms, reports, setReports, reportId, setReportId, noteId, setNoteId, termId, setTermId, answer, setAnswer, favorites, setFavorites, issued, setIssued, role, setRole, notice, setNotice }}>{children}</PreviewContext>
}
