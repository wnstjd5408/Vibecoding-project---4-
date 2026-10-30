# 고정 IP 백업 러너

MEG-131의 코드 산출물이다. **아직 배포하지 않았다.** 실제 생성, Supabase 허용 목록 변경,
첫 백업·복원 검증은 사람의 적용 승인 뒤 수행한다. 기존 백업 운영 검증은 별도로 계속한다.

비공개 운영 저장소의 GitHub-hosted job이 EC2를 켜고, EC2의 self-hosted job이 기존
백업 스크립트를 실행한 뒤, GitHub-hosted 정리 job이 EC2 정지를 확인한다.
EC2는 전용 VPC의 public subnet에 있지만 인바운드 규칙이 없다. 인터넷으로 나가는 주소는
Elastic IP 하나이고 NAT Gateway는 만들지 않는다. 관리는 Session Manager로 한다.

## 비용·적용 경계

서울 t3.small Linux 온디맨드 $0.026/시간, public IPv4 $0.005/시간,
gp3 $0.0912/GB·월을 기준으로 16 GiB 디스크와 월 730시간 EIP, 월 4시간 실행은
약 **$5.21/월**, 계속 실행하면 약 **$24.09/월**이다(2026-10-30 조회).
전송·기존 S3·세금·추가 로그 비용은 별도다. **정지해도 EIP·EBS 비용은 계속 발생한다.**
T3는 standard 모드라 CPU credit 초과 과금 대신 성능이 제한된다.

`terraform apply`는 사람의 명시적 비용 승인 전에는 실행하지 않는다. 새 root/state를 사용한다.
기존 `infra/` CD는 이 root를 자동 적용하지 않는다. 최초 apply 직후에는 설치를 위해 EC2가
실행되므로 설정이 끝나면 즉시 정지한다. user-data/AMI 변경으로 교체되면 러너 재등록이 필요하다.
AMI는 생성 당시 Ubuntu 24.04 LTS 공식 SSM parameter를 사용하고 이후 자동 교체하지 않는다.
OS 보안 업데이트는 SSM에서 정기 수행하고, AMI 교체는 별도 plan을 검토한다.

## 비공개 저장소와 신뢰 경계

1. 사람이 백업 전용 **private** 저장소를 만든다. 공개 앱 저장소에는 self-hosted runner를
   등록하지 않는다. `gh repo view OWNER/REPO --json visibility`로 PRIVATE를 확인한다.
2. 저장소 쓰기 권한은 운영자만 가진다. PR·fork·외부 dispatch용 워크플로를 추가하지 않는다.
   private 저장소라도 쓰기 권한자는 러너와 비밀값을 사용할 수 있다. Docker 권한은 호스트
   root에 준하므로 이 머신에는 다른 작업·서비스를 함께 두지 않는다.
3. OIDC는 Environment 대신 **정확한 저장소의 main 브랜치 sub**로 제한한다. private
   저장소에서 Environment/보호 규칙을 쓸 수 있는지는 GitHub 요금제에 따라 다르므로
   지원 여부를 가정하지 않는다. 제공되는 경우 main 보호와 사람 리뷰를 추가한다.
4. `operations_oidc_subject`에는 실제 발급되는 sub 형식을 사용한다. 일반 형식은
   `repo:OWNER/REPO:ref:refs/heads/main`, 저장소가 ID 포함 형식을 쓰면
   `repo:OWNER@OWNER_ID/REPO@REPO_ID:ref:refs/heads/main`이다.
   운영자가 GitHub의 OIDC 설정과 **토큰 전체를 출력하지 않는 claim 확인**으로 대조한다.
   사용자 정의 subject를 쓰는 저장소는 이 템플릿의 지원 범위 밖이다. 와일드카드로 풀지 않는다.

Terraform은 GitHub API로 private 여부를 검사하지 않는다. 사람의 위 확인과 워크플로의
`github.event.repository.private` 조건이 함께 필요하다. 공개 전환은 금지하며, 전환해야 한다면
먼저 러너를 삭제하고 역할 신뢰를 제거한다.

## Terraform 준비·권한

`terraform.tfvars`(gitignore)에 `owner`, `operations_repository`, `operations_oidc_subject`를
넣는다. 필요하면 `home_region`을 바꾸되 템플릿 `BACKUP_REGION`과 기존 S3 리전을 맞춘다.
등록 토큰·PAT·DB 비밀번호는 어떤 Terraform 변수에도 넣지 않는다.

```powershell
$env:AWS_PROFILE = "meg"
terraform init -backend-config=../backend.hcl
terraform fmt -check
terraform validate
terraform plan -out=runner.tfplan
# 여기에서 생성 목록·권한·비용을 사람이 검토하고 적용을 승인한다.
# 승인 후에만: terraform apply runner.tfplan
```

위 명령은 이 디렉터리에서 실행한다. state key는 `infra/backup-runner.tfstate`이며 기존
백업 state를 가져오지 않는다. plan/state/tfvars는 공개 업로드하지 않는다.

적용 주체에게는 VPC/subnet/route/IGW/security group/EIP/EC2/EBS 생성·태그·정리 권한,
이름이 `<owner>-backup-runner`로 시작하는 IAM role/profile/policy 관리와 해당 profile의
EC2 `iam:PassRole`, 공식 AMI parameter 조회, 기존 GitHub OIDC provider 조회,
Terraform backend 읽기·쓰기·잠금 권한이 필요하다. 기존 Infra CD 역할의 권한을 넓히지 않는다.
실제 plan의 리소스 범위로 사람의 적용 역할을 확인한다. 새 권한이 부족하면 승인을 요청한다.

생성되는 역할은 둘이다.

| 역할 | 권한 |
|---|---|
| EC2 instance profile | SSM 등록 상태 보고와 Session Manager 채널만. Parameter Store·S3·EC2 제어 권한 없음 |
| lifecycle OIDC role | 이 인스턴스 한 대 Start/Stop, 해당 리전 DescribeInstances/DescribeInstanceStatus |

기존 S3 업로드 역할은 재사용하며 EC2 profile에 붙이지 않는다. SSM 접속자의
`StartSession`/`ResumeSession`/`TerminateSession` 권한도 별도로 필요하다.

## 적용 승인 뒤 최초 설정

1. Terraform output `supabase_allow_cidr`를 Supabase Network Restrictions에 **추가**한다.
   기존 운영자 `/32`는 보존한다. `0.0.0.0/0` 허용이나 TLS 검증 해제는 하지 않는다.
   이 작업은 이 Terraform이 수행하지 않는다.
2. SSM에서 `sudo cloud-init status --wait`로 설치 완료를 확인한다. 설치 오류에 비밀값은
   없지만 로그 전체를 공개 PR에 붙이지 않는다. EIP 연결까지 apt 설치가 재시도된다.
3. private 저장소 Settings → Actions → Runners → New self-hosted runner에서 Linux x64
   등록 토큰을 발급한다(1시간 유효). SSM에서 `sudo /usr/local/sbin/register-backup-runner`를
   실행하고 숨김 입력 프롬프트에 토큰만 붙인다. 쉘 명령줄·GitHub Secret·Terraform에 넣지 않는다.
   토큰은 환경변수로만 config.sh에 전달하고 출력은 보호된 임시 파일 후 삭제한다.
4. GitHub에서 `backup-fixed-ip` 러너가 Idle이고 라벨이 `self-hosted`, `Linux`, `X64`,
   `backup-fixed-ip`인지 확인한다. `sudo systemctl list-timers backup-runner-stop.timer`도 확인한다.
   설정 중에도 부팅 60분 후 정지하므로 시간이 부족하면 정지/시작 후 다시 연결한다.
5. private 저장소에 아래 설정을 넣는다. Secret 값은 기존 화면/비밀 저장소에서 사람이
   확인해 입력한다. 기존 GitHub Secret 값은 API로 다시 읽을 수 없다.

| 종류 | KEY | 값의 출처 |
|---|---|---|
| Secret | `RUNNER_LIFECYCLE_ROLE_ARN` | 새 root의 `lifecycle_role_arn` output |
| Variable | `RUNNER_INSTANCE_ID` | 새 root의 `instance_id` output |
| Variable | `SOURCE_COMMIT` | 사람이 검토하고 main에 병합한 앱 저장소의 전체 40자리 commit SHA |
| Secret | `AWS_ROLE_ARN`, `BACKUP_BUCKET` | 기존 `infra/db-backup` output |
| Secret | `SUPABASE_DB_URL`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY` | 기존 백업 전용 설정(세션 풀러 5432) |
| Variable | `GLOSSARY_IMAGE_BUCKET`, `NOTE_IMAGE_BUCKET` | 실제 이미지 버킷 이름(기존 방식과 동일) |

6. TLS CA 진단 수정 PR #76을 먼저 검토·병합하고 이를 포함하는 `SOURCE_COMMIT`을 고른다.
   이 구현은 TLS 검증을 낮추거나 CA 변경을 중복하지 않는다. 소스는 매번 main 최신을
   따라가지 않고 승인된 SHA에 고정한다. 변경 때마다 사람이 새 SHA를 검토한다.
7. 기존 `infra/db-backup/terraform.tfvars`의 `backup_oidc_subject`를 위 운영 저장소 sub로
   지정한다. 그 root에서 plan으로 **기존 업로드 역할의 trust만 교체**되는지 확인한다.
   사람 승인 후 적용한다. 기본값 null은 기존 공개 저장소 Environment 신뢰를 그대로 유지한다.
   새 역할을 추가하지 않으므로 버킷의 업로드 허용 역할과 보관 정책은 바뀌지 않는다.
8. `templates/db-backup.yml`을 private 저장소 `.github/workflows/db-backup.yml`로 복사한다.
   이 공개 저장소에서 실행하는 워크플로가 아니라 설치용 템플릿이다. 소스 코드를 private
   저장소에 복제할 필요는 없다. public 소스를 고정 SHA로 checkout한다.
9. EC2를 정지하고 stopped 확인 후 private 워크플로를 수동 실행한다. DB 덤프·S3 업로드·이미지
   대조가 성공하고 stop job이 EC2 stopped까지 확인하는지 본다. EIP와 TLS·DB 연결도 확인한다.
   이미지 버킷이 없어서 skip되면 이미지 AC 성공으로 보지 않는다.
10. 전환 검증 동안 기존 공개 `DB Backup` 예약 실행을 disable하여 중복 실행을 막는다.
    성공 후 private 주간 스케줄만 유지한다. rollback 시에는 private 스케줄을 먼저 disable,
    EC2 정지, 기존 역할 `backup_oidc_subject=null` 복구를 plan/승인 후 적용한다.
    공개 러너로 되돌리는 것만으로 Network Restrictions 문제는 해결되지 않는다.

## 정지·오류·수명 관리

- start job은 stopped 상태를 확인하고 시작한다. 첫 설정 후 실행 중인 인스턴스는 먼저 정지한다.
  concurrency는 한 번에 한 백업만 허용한다. stop job은 성공/실패/취소 때 실행하도록 작성했다.
- GitHub 장애나 취소로 stop job이 실행되지 않아도 systemd timer가 **매 부팅 60분 후** 정지한다.
  이는 OS가 정상 동작한다는 전제다. OS 장애까지 보장하는 외부 watchdog은 아니며,
  AWS 비용 알림과 인스턴스 상태도 운영자가 확인한다. 백업 job 제한은 30분이다.
- runner가 offline이면 self-hosted job이 큐에 남을 수 있다. job timeout은 대기 시간 제한이
  아니다. 이때 운영자가 workflow를 취소하고 GitHub 등록/SSM 서비스 상태를 확인한다.
  EC2는 타이머로 정지된다. 성공 기록이 없는 실행을 백업 성공으로 계산하지 않는다.
- 덤프와 진단 로그는 암호화된 EBS에만 임시로 저장한다. job의 always 정리 단계가 지우고,
  취소/정전으로 남으면 러너 서비스 다음 시작 전에 Docker 컨테이너와 `_work`·`_diag`를 정리한다.
  정리 실패는 서비스 시작 실패로 이어진다. 삭제는 디스크 보안 삭제를 뜻하지 않는다.
- 등록 자격증명은 `/opt/actions-runner`의 암호화된 EBS에 지속된다. 머신을 다른 용도로 재사용하지
  않는다. 손상/탈취가 의심되면 GitHub 러너 삭제, 비밀값 폐기·재발급, EC2 교체 후 재등록한다.
- 처음 받는 runner 2.338.2 아카이브는 공식 SHA256을 검사한다. GitHub runner 자동 업데이트는
  켜 둔다. 버전 지원 기간/업데이트 실패를 확인하고 부팅 이미지의 핀도 주기적으로 갱신한다.
- 정리할 때 private workflow disable → EC2 stopped → GitHub runner 삭제 → 해당 root
  destroy plan 검토/승인 → EIP 반환과 볼륨 삭제 확인 순서다. 기존 백업 버킷은 이 root에 없다.

## 로컬 검증과 실제 배포 검증

```powershell
terraform init -backend=false
terraform validate
terraform test
uv run --with pyyaml python tests/check_workflow.py
actionlint -config-file tests/actionlint.yaml -shellcheck= -pyflakes= templates/db-backup.yml
```

Terraform test는 **mock provider**만 사용한다(테스트 안의 apply도 모의 실행).
인바운드 차단·암호화·IMDSv2·정지 타이머·OIDC 범위·단일 인스턴스 권한·잘못된 입력을 확인한다.
템플릿 검증은 트리거/신뢰 경계와 고정 소스, 정리 경로를 확인한다.
실제 AWS plan/apply, OS 부팅·SSM 등록, private runner 연결, 취소 시 정지, 실제 DB 백업과
복원은 아직 검증하지 않았다. 적용 후 이 순서로 확인하고 기존 운영 검증에 결과를 남긴다.

참고: [GitHub runner 보안](https://docs.github.com/en/actions/reference/security/secure-use),
[AWS public IPv4 비용](https://aws.amazon.com/vpc/pricing/),
[GitHub runner 릴리스](https://github.com/actions/runner/releases/tag/v2.338.2).

Session Manager 최소 정책은 [AWS 공식 예제](https://docs.aws.amazon.com/systems-manager/latest/userguide/getting-started-create-iam-instance-profile.html)를 따른다.
