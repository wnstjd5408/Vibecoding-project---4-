// F5-1c 용어 수정 / F5-1e 새 용어 폼(MEG-82). term이 null이면 새 용어다.
import { useEffect, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { Button, TextField } from '../../components/index.ts'
import { useOperatorGuard } from '../useOperatorGuard.ts'
import { ConfirmDialog } from './ConfirmDialog.tsx'
import { deleteDescription, saveTerm } from './glossaryApi.ts'
import type { GlossaryTerm, ImageChange } from './glossaryApi.ts'
import { IMAGE_REJECTED_MESSAGE, IMAGE_TYPES, isAllowedImage } from './imageRules.ts'
import styles from './Glossary.module.css'

// 화면 문구. 실패 안내는 목업에 화면이 없어 임시 문구다(문구 미정, 확정되면 이 한 곳만 고친다).
const MESSAGES = {
  required: '용어 이름과 설명을 입력해 주세요.',
  duplicate: '이미 등록된 용어예요. 목록에서 선택해 수정해 주세요.',
  saveFailed: '저장하지 못했어요. 잠시 뒤에 다시 시도해 주세요.',
  deleteFailed: '사전 설명을 삭제하지 못했어요. 잠시 뒤에 다시 시도해 주세요.',
  // 새 용어·수정 안내. "용어 삭제"가 아니라 "사전 설명 삭제"의 뜻이다(Q-N4, D-060).
  noticeCreate: '안내: 저장하면 같은 용어의 AI 설명이 무효가 돼요.',
  noticeEdit: '안내: 저장하면 이 용어의 AI 설명이 무효가 돼요. 사전 설명을 삭제해도 AI 설명과 신고는 남아요.',
} as const

type TermFormProps = {
  term: GlossaryTerm | null
  // 이미 등록된 용어. 이름이 겹치는지 보는 데 쓴다.
  terms: GlossaryTerm[]
  onSaved: (term: GlossaryTerm) => void
  onDeleted: (term: GlossaryTerm) => void
  onCancel: () => void
}

type Upload = { file: File; url: string }

export default function TermForm({ term, terms, onSaved, onDeleted, onCancel }: TermFormProps) {
  const creating = term === null
  const { onApiError } = useOperatorGuard()
  const [label, setLabel] = useState(term?.label ?? '')
  const [description, setDescription] = useState(term?.description ?? '')
  // 새로 고른 이미지(저장 전). 고른 즉시 미리 보고, 저장할 때 올린다.
  const [upload, setUpload] = useState<Upload | null>(null)
  const [imageRemoved, setImageRemoved] = useState(false)
  // 거절된 파일이 입력 칸에 남지 않도록 칸을 새로 그린다.
  const [inputKey, setInputKey] = useState(0)
  const [imageError, setImageError] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  // 미리보기 주소는 쓰고 나면 해제한다.
  useEffect(
    () => () => {
      if (upload) URL.revokeObjectURL(upload.url)
    },
    [upload],
  )

  const shownImage = upload?.url ?? (imageRemoved ? null : (term?.imageUrl ?? null))

  function handlePick(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    // 허용되지 않는 파일은 안내만 하고 아무것도 바꾸지 않는다(저장 대상에 넣지 않는다).
    if (!isAllowedImage(file)) {
      setImageError(IMAGE_REJECTED_MESSAGE)
      setInputKey((key) => key + 1)
      return
    }
    setImageError('')
    setImageRemoved(false)
    setUpload({ file, url: URL.createObjectURL(file) })
  }

  function handleRemoveImage() {
    setUpload(null)
    setImageRemoved(true)
    setImageError('')
    setInputKey((key) => key + 1)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    const name = label.trim()
    if (!name || !description.trim()) {
      setError(MESSAGES.required)
      return
    }
    if (terms.some((other) => other.id !== term?.id && other.label.toLowerCase() === name.toLowerCase())) {
      setError(MESSAGES.duplicate)
      return
    }
    const image: ImageChange = upload ? { kind: 'upload', file: upload.file } : imageRemoved ? { kind: 'remove' } : { kind: 'keep' }
    setBusy(true)
    setError('')
    try {
      onSaved(await saveTerm(term?.id ?? null, { label: name, description: description.trim() }, image))
    } catch (failure) {
      // 권한 오류면 로그인 상태를 다시 읽어 경로 보호가 화면을 내보낸다. 그 밖에는 저장하지 못했다고 알린다.
      if (!onApiError(failure)) setError(MESSAGES.saveFailed)
      setBusy(false)
    }
  }

  async function handleDelete() {
    if (!term || busy) return
    setBusy(true)
    try {
      await deleteDescription(term.id)
      onDeleted(term)
    } catch (failure) {
      setConfirmingDelete(false)
      if (!onApiError(failure)) setError(MESSAGES.deleteFailed)
      setBusy(false)
    }
  }

  return (
    <form className={styles.card} onSubmit={handleSubmit}>
      <h2 className={styles.formTitle}>{creating ? '새 용어' : '용어 수정'}</h2>
      <TextField label="용어 이름" required maxLength={100} value={label} onChange={(event) => setLabel(event.target.value)} />
      <TextField
        label="설명"
        multiline
        required
        className={styles.description}
        value={description}
        onChange={(event) => setDescription(event.target.value)}
      />

      <div className={styles.imageField}>
        {shownImage ? (
          <>
            <span className={styles.label}>이미지</span>
            <div className={styles.imageRow}>
              <img className={styles.image} src={shownImage} alt="설명 이미지 미리보기" />
              <Button onClick={handleRemoveImage}>이미지 삭제</Button>
            </div>
          </>
        ) : null}
        <div>
          <label className={styles.label} htmlFor="glossary-image">
            이미지 올리기 (선택, 한 장씩)
          </label>
          <input
            key={inputKey}
            id="glossary-image"
            type="file"
            accept={IMAGE_TYPES.join(',')}
            aria-describedby={imageError ? 'glossary-image-error' : undefined}
            onChange={handlePick}
          />
        </div>
        {imageError ? (
          <p id="glossary-image-error" role="alert" className={styles.error}>
            오류: {imageError}
          </p>
        ) : null}
      </div>

      <p className={styles.notice}>{creating ? MESSAGES.noticeCreate : MESSAGES.noticeEdit}</p>
      {error ? (
        <p role="alert" className={styles.error}>
          오류: {error}
        </p>
      ) : null}
      <div className={styles.row}>
        <Button type="submit" variant="primary" aria-disabled={busy ? 'true' : undefined}>
          저장
        </Button>
        {creating ? <Button onClick={onCancel}>취소</Button> : null}
      </div>

      {!creating ? (
        <div className={styles.divider}>
          <Button onClick={() => setConfirmingDelete(true)}>사전 설명 삭제</Button>
        </div>
      ) : null}
      {confirmingDelete && term ? (
        <ConfirmDialog title="사전 설명을 삭제할까요?" onClose={() => setConfirmingDelete(false)}>
          <p className={styles.dialogTerm}>{term.label}</p>
          <p className={styles.dialogBody}>설명과 이미지가 사전에서 사라져요. AI 설명과 신고는 남아요.</p>
          <div className={styles.row}>
            <Button onClick={handleDelete} aria-disabled={busy ? 'true' : undefined}>
              삭제하기
            </Button>
            <Button variant="primary" onClick={() => setConfirmingDelete(false)}>
              취소
            </Button>
          </div>
        </ConfirmDialog>
      ) : null}
    </form>
  )
}
