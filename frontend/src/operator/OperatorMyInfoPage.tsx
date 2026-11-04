// F4-3d 운영자 내 정보(MEG-66). 운영자 셸 안에서 E03의 표시 이름과 역할만 읽기 전용으로 보여 준다. 이메일은 MVP에서 뺐다(목업에는 이메일 행이 있지만 티켓 제약을 따른다).
// 셸이 운영자로 확인한 뒤에야 이 화면을 열므로 로그인 상태를 읽는 중이거나 방문자인 경우는 여기서 다루지 않는다.
import { ROLE_LABEL } from '../account/roleLabel.ts'
import { useAuth } from '../auth/useAuth.ts'
import styles from './OperatorMyInfoPage.module.css'

export default function OperatorMyInfoPage() {
  const { role, displayName } = useAuth()
  return (
    <main>
      <h1 className={styles.title}>내 정보</h1>
      <section aria-labelledby="operator-my-info-account" className={styles.box}>
        <h2 id="operator-my-info-account" className={styles.boxTitle}>
          계정
        </h2>
        <dl className={styles.details}>
          <dt>표시 이름</dt>
          <dd>{displayName ?? '-'}</dd>
          <dt>역할</dt>
          <dd>{role === 'visitor' ? '-' : ROLE_LABEL[role]}</dd>
        </dl>
        <p className={styles.note}>이 화면에서는 볼 수만 있어요.</p>
      </section>
    </main>
  )
}
