// F5-1c 용어 수정 / F5-1e 새 용어 폼(MEG-82). term이 null이면 새 용어다.
import { useEffect, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { isApiError } from '../../api/client.ts'
import { Button, StateMessage, TextField } from '../../components/index.ts'
import { useOperatorApi } from '../useOperatorApi.ts'
import { ConfirmDialog } from './ConfirmDialog.tsx'
import { ImageNotSavedError, deleteDescription, readTerm, saveTerm, termKey } from './glossaryApi.ts'
import type { GlossaryDetail, GlossaryImage, GlossaryTerm, ImageChange } from './glossaryApi.ts'
import { IMAGE_REJECTED_MESSAGE, IMAGE_TYPES, isAllowedImage } from './imageRules.ts'
import styles from './Glossary.module.css'

// 화면 문구. 실패 안내는 목업에 화면이 없어 임시 문구다(문구 미정, 확정되면 이 한 곳만 고친다).
const MESSAGES = {
  required: '용어 이름과 설명을 입력해 주세요.',
  duplicate: '이미 등록된 용어예요. 목록에서 선택해 수정해 주세요.',
  saveFailed: '저장하지 못했어요. 잠시 뒤에 다시 시도해 주세요.',
  // 설명은 저장됐고 이미지만 실패했다. 폼은 서버에 저장된 상태로 다시 그려지므로 이미지를 다시 골라야 한다.
  imageNotSaved: '설명은 저장했지만 이미지를 바꾸지 못했어요. 이미지를 다시 골라 저장해 주세요.',
  deleteFailed: '사전 설명을 삭제하지 못했어요. 잠시 뒤에 다시 시도해 주세요.',
  loadFailed: '용어를 불러오지 못했어요',
  loadFailedHint: '잠시 뒤에 다시 시도해 주세요.',
  loading: '용어를 불러오는 중이에요',
  // 서버가 이름 변경을 지원하지 않아 기존 용어의 이름은 고칠 수 없다. 다른 이름이면 다른 용어다.
  labelFixed: '이름은 바꿀 수 없어요. 다른 이름이 필요하면 새 용어로 등록해 주세요.',
  // 새 용어·수정 안내. "용어 삭제"가 아니라 "사전 설명 삭제"의 뜻이다(Q-N4, D-060).
  noticeCreate: '안내: 저장하면 같은 용어의 AI 설명이 무효가 돼요.',
  noticeEdit: '안내: 저장하면 이 용어의 AI 설명이 무효가 돼요. 사전 설명을 삭제해도 AI 설명과 신고는 남아요.',
} as const

type TermFormProps = {
  term: GlossaryTerm | null
  // 이미 등록된 용어. 새 용어의 이름이 겹치는지 보는 데 쓴다.
  terms: GlossaryTerm[]
  // 저장 결과. imageError가 있으면 설명만 저장되고 이미지 단계가 실패한 것이다.
  onSaved: (term: GlossaryTerm, imageError: string | null) => void
  onDeleted: (term: GlossaryTerm) => void
  onCancel: () => void
}

type Detail = { termId: number; detail: GlossaryDetail } | { termId: number; failed: true }

// 기존 용어는 E06으로 설명과 이미지를 읽은 뒤 폼을 보인다. 폼의 입력은 읽은 값으로 시작하므로 용어를 바꾸거나 저장한 뒤에는 이 컴포넌트를 새로 그린다.
export default function TermForm(props: TermFormProps) {
  const operatorFetch = useOperatorApi()
  const termId = props.term?.id
  const [attempt, setAttempt] = useState(0)
  const [loaded, setLoaded] = useState<(Detail & { attempt: number }) | null>(null)

  useEffect(() => {
    if (termId === undefined) return
    let live = true
    readTerm(operatorFetch, termId).then(
      (detail) => live && setLoaded({ termId, detail, attempt }),
      () => live && setLoaded({ termId, failed: true, attempt }),
    )
    return () => {
      live = false
    }
  }, [termId, attempt, operatorFetch])

  if (termId === undefined) return <TermFormBody {...props} detail={{ description: '', images: [] }} />
  const current = loaded?.termId === termId && loaded.attempt === attempt ? loaded : null
  if (!current) return <StateMessage kind="loading" title={MESSAGES.loading} />
  if ('failed' in current) {
    return (
      <StateMessage
        kind="error"
        title={MESSAGES.loadFailed}
        description={MESSAGES.loadFailedHint}
        action={<Button onClick={() => setAttempt((count) => count + 1)}>다시 시도</Button>}
      />
    )
  }
  return <TermFormBody {...props} detail={current.detail} />
}

type Upload = { file: File; url: string }

function TermFormBody({ term, terms, detail, onSaved, onDeleted, onCancel }: TermFormProps & { detail: GlossaryDetail }) {
  const creating = term === null
  const operatorFetch = useOperatorApi()
  const [label, setLabel] = useState(term?.label ?? '')
  const [description, setDescription] = useState(detail.description)
  // 새로 고른 이미지(저장 전). 고른 즉시 미리 보고, 저장할 때 올린다.
  const [upload, setUpload] = useState<Upload | null>(null)
  // 저장할 때 지울 기존 이미지. 누르면 화면에서 바로 사라지고 저장할 때 서버에서 지운다.
  const [removedIds, setRemovedIds] = useState<number[]>([])
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

  const shownImages: GlossaryImage[] = detail.images.filter((image) => !removedIds.includes(image.id))

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
    setUpload({ file, url: URL.createObjectURL(file) })
  }

  function handleDiscardUpload() {
    setUpload(null)
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
    // 새 용어의 이름이 이미 있는 용어와 같은 key면 서버가 기존 용어를 덮어쓰므로 미리 막는다.
    if (creating && terms.some((other) => other.key === termKey(name))) {
      setError(MESSAGES.duplicate)
      return
    }
    const image: ImageChange = { removeIds: removedIds, upload: upload?.file ?? null }
    setBusy(true)
    setError('')
    try {
      onSaved(await saveTerm(operatorFetch, { label: name, description: description.trim() }, image), null)
    } catch (failure) {
      // 권한 상실이면 operatorFetch가 로그인 상태를 다시 읽어 경로 보호가 화면을 내보낸다. 그 밖에는 저장하지 못했다고 알린다.
      if (failure instanceof ImageNotSavedError) {
        // 설명은 저장됐다. 화면은 서버 상태로 다시 읽어 그린다. 서버가 파일을 거절했으면 그 이유(형식·크기)도 알린다.
        const cause = failure.cause
        const rejected = isApiError(cause, 'payload_too_large') || isApiError(cause, 'unsupported_media_type') || isApiError(cause, 'validation_failed')
        onSaved(failure.saved, rejected ? `${MESSAGES.imageNotSaved} ${IMAGE_REJECTED_MESSAGE}` : MESSAGES.imageNotSaved)
      } else {
        setError(MESSAGES.saveFailed)
      }
    } finally {
      // 같은 용어를 계속 고칠 수 있도록 성공해도 처리 중 상태를 푼다.
      setBusy(false)
    }
  }

  async function handleDelete() {
    if (!term || busy) return
    setBusy(true)
    try {
      await deleteDescription(operatorFetch, term.id)
      onDeleted(term)
    } catch {
      // 권한 상실이면 operatorFetch가 이미 처리했다. 그 밖에는 창을 닫고 폼에서 알린다.
      setConfirmingDelete(false)
      setError(MESSAGES.deleteFailed)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className={styles.card} onSubmit={handleSubmit}>
      <h2 className={styles.formTitle}>{creating ? '새 용어' : '용어 수정'}</h2>
      <TextField
        label="용어 이름"
        required
        maxLength={200}
        value={label}
        readOnly={!creating}
        hint={creating ? undefined : MESSAGES.labelFixed}
        onChange={(event) => setLabel(event.target.value)}
      />
      <TextField
        label="설명"
        multiline
        required
        className={styles.description}
        value={description}
        onChange={(event) => setDescription(event.target.value)}
      />

      <div className={styles.imageField}>
        {shownImages.length > 0 || upload ? <span className={styles.label}>이미지</span> : null}
        {shownImages.map((image) => (
          <div key={image.id} className={styles.imageRow}>
            <img className={styles.image} src={image.url} alt={image.alt || '설명 이미지'} />
            <Button onClick={() => setRemovedIds((ids) => [...ids, image.id])}>이미지 삭제</Button>
          </div>
        ))}
        {upload ? (
          <div className={styles.imageRow}>
            <img className={styles.image} src={upload.url} alt="새 이미지 미리보기" />
            <Button onClick={handleDiscardUpload}>이미지 삭제</Button>
          </div>
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
