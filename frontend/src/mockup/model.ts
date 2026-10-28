import { createContext, useContext } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import type { Note, Report, Term } from './data.ts'

type Setter<T> = Dispatch<SetStateAction<T>>
export type PreviewModel = {
  notes: Note[]; setNotes: Setter<Note[]>; adminNotes: Note[]; setAdminNotes: Setter<Note[]>
  terms: Term[]; setTerms: Setter<Term[]>; reports: Report[]; setReports: Setter<Report[]>
  noteId: number; setNoteId: Setter<number>; termId: number; setTermId: Setter<number>
  reportId: number; setReportId: Setter<number>
  answer: string; setAnswer: Setter<string>; favorites: number[]; setFavorites: Setter<number[]>
  issued: { email: string; name: string }; setIssued: Setter<{ email: string; name: string }>
  role: 'visitor' | 'member' | 'operator'; setRole: Setter<'visitor' | 'member' | 'operator'>
  notice: string; setNotice: Setter<string>
}
export const PreviewContext = createContext<PreviewModel | null>(null)
export function usePreview() {
  const value = useContext(PreviewContext)
  if (!value) throw new Error('PreviewProvider is required')
  return value
}
