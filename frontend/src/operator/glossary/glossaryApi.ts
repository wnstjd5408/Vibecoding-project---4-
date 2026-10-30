// 사전 용어 서버 호출(API spec v0.2 E19~E23)을 모은 파일이다. 화면은 이 파일의 함수만 부른다.
//
// TODO(MEG-82): E19~E23 명세(MEG-27 첨부)를 받으면 아래 함수 본문을 apiFetch 호출로 바꾼다. 함수 모양(인자·반환)과 화면은 그대로 둔다.
// 지금은 명세가 저장소에 없어 경로·필드·오류 code를 정할 수 없으므로, 메모리 가짜 저장소로 화면을 먼저 확인한다.
// 이 저장소는 새로 고치면 사라지고, 합성 데이터만 담는다.

export type GlossaryTerm = {
  id: number
  label: string
  description: string
  imageUrl: string | null
}

export type TermInput = { label: string; description: string }

// 저장할 때 이미지를 어떻게 할지: 그대로 둔다 / 지운다 / 새로 올린다
export type ImageChange = { kind: 'keep' } | { kind: 'remove' } | { kind: 'upload'; file: File }

// 합성 데이터. 실제 용어가 아니다.
let store: GlossaryTerm[] = [
  { id: 1, label: 'DNS', description: '도메인 이름을 서버의 숫자 주소로 바꿔 주는 이름 찾기 서비스예요.', imageUrl: null },
  { id: 2, label: '패킷', description: '네트워크로 보내는 데이터를 잘게 나눈 조각이에요.', imageUrl: null },
  { id: 3, label: '라우터', description: '패킷이 갈 길을 골라 전달하는 장비예요.', imageUrl: null },
  { id: 4, label: '캐시', description: '자주 쓰는 데이터를 가까운 곳에 잠시 보관해 두는 방식이에요.', imageUrl: null },
]
let nextId = 5

// E19: 사전 용어 목록
export async function listTerms(): Promise<GlossaryTerm[]> {
  return store.map((term) => ({ ...term }))
}

// E20·E22·E23: id가 없으면 새 용어를 등록하고, 있으면 수정한다. 이미지는 image가 정한 대로 바꾼다.
export async function saveTerm(id: number | null, input: TermInput, image: ImageChange): Promise<GlossaryTerm> {
  const existing = id === null ? null : (store.find((term) => term.id === id) ?? null)
  const imageUrl =
    image.kind === 'upload' ? URL.createObjectURL(image.file) : image.kind === 'remove' ? null : (existing?.imageUrl ?? null)
  const saved: GlossaryTerm = { id: existing?.id ?? nextId++, label: input.label, description: input.description, imageUrl }
  store = existing ? store.map((term) => (term.id === saved.id ? saved : term)) : [...store, saved]
  return { ...saved }
}

// E21: 사전 설명 삭제. 설명과 이미지만 지우고 용어 자체(terms 행)는 서버에 남는다(D-060). 사전 목록에서는 사라진다.
export async function deleteDescription(id: number): Promise<void> {
  store = store.filter((term) => term.id !== id)
}
