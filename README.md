# Vibecoding project 4

처음 왔다면 아래 [clone 후 할 일](#clone-후-할-일)의 1번부터 진행한다. 전체 약 30분이 걸린다.

3명이 PMF(제품-시장 적합성)를 검증하는 프로젝트다. 제품은 아직 정하지 않았고 정해지면 [docs/prd.md](docs/prd.md)에 적는다. 이슈와 일정은 Linear(팀 키 `MEG`, 프로젝트 Megazoneproject)에서, 소통은 Slack `#project-mangement`에서 한다.

## clone 후 할 일

1. **GitHub 초대 수락** (2분). 이메일이나 GitHub 알림으로 온 저장소 초대를 수락한다.
2. **clone과 로그인** (5분).
   ```bash
   git clone https://github.com/wnstjd5408/Vibecoding-project---4-.git
   cd Vibecoding-project---4-
   gh auth login
   ```
   `gh`가 없으면 [GitHub CLI](https://cli.github.com/)를 먼저 설치한다.
3. **커밋 작성자 설정** (3분). 공개 저장소라 커밋에 적힌 이메일이 그대로 공개된다. GitHub Settings → Emails에서 `...@users.noreply.github.com` 주소를 확인해 쓴다.
   ```bash
   git config user.name "<GitHub 아이디>"
   git config user.email "<noreply 주소>"
   ```
4. **Linear 연결** (10분). 워크스페이스 megazoneproject에 가입하고 팀 MEG에 들어간다. Settings의 GitHub 연동 화면에서 개인 GitHub 계정을, Slack 연동 화면에서 개인 Slack 계정을 연결해야 PR과 이슈가 내 이름으로 이어진다.
5. **알림 켜기** (5분). Linear Settings → Notifications → Slack에서 Slack 알림을 켜고 Slack `#project-mangement` 채널에 들어간다.

줄바꿈은 `.gitattributes`가 LF로 맞추므로 따로 설정하지 않는다.

## 작업 흐름

이슈 하나는 브랜치 하나, PR 하나로 끝낸다.

1. 이슈 고르기. Linear에서 Todo 이슈를 고르고 담당자를 나로 바꾼다.
2. 브랜치 만들기. 이름은 `<이슈ID소문자>-<짧은-설명>`이다. Linear의 "Copy git branch name" 버튼이 주는 `js2002232/...` 형식은 쓰지 않는다.
   ```bash
   git switch main && git pull
   git switch -c meg-12-first-experiment
   ```
3. 커밋하고 PR 열기. 브랜치 안의 커밋 메시지는 자유롭게 쓴다. PR 제목은 `<type>(<이슈ID>): <한국어 설명>` 형식이고 type은 `feat`, `fix`, `docs`, `chore` 중 하나다. 예: `docs(MEG-12): 첫 실험 설계 문서 추가`. 제목이 틀리면 `Check PR title` 검사가 실패한다.
4. 템플릿 채우기. PR 본문 템플릿에 AC별 검증 결과와 김준성에게 묻는 결정 요청을 적는다. PR을 열면 Linear 이슈가 In Review로 바뀐다.
5. 리뷰와 머지. 모든 PR은 김준성(@wnstjd5408)의 승인이 있어야 squash로 머지된다. 머지되면 Linear 이슈가 Done으로 바뀌고 브랜치는 자동 삭제된다.

기능이 커서 하루이틀 안에 끝나지 않으면 Linear에서 하위 이슈로 나눠 PR을 여러 개로 올리고 한 번에 리뷰할 양을 줄여 김준성의 리뷰가 병목이 되지 않게 한다.

## 막혀 있는 것

main에는 아래 규칙이 걸려 있어서 우회할 수 없다.

| 규칙 | 결과 |
|---|---|
| main 직접 푸시 금지 | 모든 변경은 PR로만 들어간다 |
| 승인 1건과 코드 소유자(김준성) 리뷰 필수 | 승인 없이는 머지 버튼이 잠긴다 |
| squash 머지만 허용, 선형 기록 | main에는 PR 하나가 커밋 하나로 남는다 |
| main 삭제·force push 금지 | 기록을 덮어쓸 수 없다 |

김준성이 직접 올린 PR은 본인이 승인할 수 없다. 이때는 리뷰 후 PR 화면의 bypass 체크박스로 머지한다.

## 지켜야 할 것

- API 키, 토큰, 비밀번호는 코드, 이슈, PR, 로그에 쓰지 않는다. 비밀값은 환경변수로만 쓰고 `.env`는 커밋하지 않는다. `.gitignore`가 `.env`를 막아 둔다.
- 이슈 범위 밖의 수정은 새 이슈로 만든다.
- AI 에이전트(Claude Code, Codex 등)에게 작업을 맡길 때는 [AGENTS.md](AGENTS.md)를 따르게 한다. Claude Code는 [CLAUDE.md](CLAUDE.md)를 통해 AGENTS.md를 자동으로 읽는다.

## 문서

| 문서 | 내용 |
|---|---|
| [AGENTS.md](AGENTS.md) | 사람과 AI 에이전트가 함께 따르는 작업 규칙 |
| [docs/prd.md](docs/prd.md) | 문제, 가설, 성공 지표 (작성 전) |
| [docs/experiments.md](docs/experiments.md) | 가설 검증 실험 기록 (작성 전) |
| [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md) | PR 본문 템플릿 |

## 개발 환경

Python과 React로 개발할 예정이다. 구체적인 버전, 프레임워크, 설치 절차는 기술 스택이 확정되면 이 섹션에 추가한다.
