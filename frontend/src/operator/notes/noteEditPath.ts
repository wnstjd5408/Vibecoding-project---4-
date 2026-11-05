import { operatorPaths } from '../../routes/paths.ts'

// noteEdit 경로에 노트 id를 채운다.
export function noteEditPath(noteId: number | string): string {
  return operatorPaths.noteEdit.replace(':noteId', String(noteId))
}
