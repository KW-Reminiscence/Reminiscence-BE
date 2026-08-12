# Reminiscence rpi5 운영 절차

대상은 `rpi5-server`의 production 단일 instance입니다. 외부 주소는
`https://reminiscence.leehyowon14.dev`, host loopback port는 API `3010`, web
`3011`입니다. rpi5에서는 source build를 하지 않고 GHCR ARM64 digest image만
pull합니다.

## 1. Host directory와 비밀값

```text
/home/ubuntu/apps/reminiscence/production/
  application-secrets.json  # 0600, Git 제외
  data/                     # 0750, versioned JSON
  supertonic3/              # model assets
  backups/                  # checksummed JSON snapshots
  docker-compose.yml
  .env                      # image/path bootstrap only
  release.json              # FE·API commit·digest, OpenAPI hash와 snapshot
```

다음 파일을 example에서 시작해 host에서 직접 작성합니다.

```bash
install -d -m 0750 /home/ubuntu/apps/reminiscence/production/data
install -m 0600 deploy/application-secrets.example.json \
  /home/ubuntu/apps/reminiscence/production/application-secrets.json
install -m 0640 deploy/configuration.example.json \
  /home/ubuntu/apps/reminiscence/production/data/configuration.json
```

`application-secrets.json`에는 Guardian 평문 비밀번호, Tablet pairing code,
codex-lb key와 SMTP credential을 입력합니다. 이 값은 채팅, Git, CI log와
snapshot에 넣지 않습니다. `configuration.json`의 사진·이름·일정은 실제
사용자용 값으로 바꾸고 `runtime.public_origin`은 production URL과 정확히
일치시킵니다.

배포 전 권한을 확인합니다.

```bash
stat -c '%a %U:%G %n' \
  /home/ubuntu/apps/reminiscence/production \
  /home/ubuntu/apps/reminiscence/production/data \
  /home/ubuntu/apps/reminiscence/production/application-secrets.json
```

secret은 `600`, production과 data directory는 `750`이어야 합니다.

## 2. 최초 legacy JSON 전환

현재 data가 `schema_version` 없는 demo 형식이면 일반 배포보다 먼저 한 번만
offline 전환합니다. 정상 배포 snapshot은 strict current schema만 받으므로,
legacy 원본은 별도 directory에 그대로 보존해야 합니다.

1. GitHub Actions의 `CI/CD` workflow를 수동 실행하고
   `apply_json_migrations`를 승인합니다.
2. script가 maintenance에 진입하고 기존 API를 중지합니다.
3. schema와 무관한 `legacy_snapshot`이 모든 JSON 원본, 정확한 파일 목록과
   SHA-256을 atomic directory로 보존합니다.
4. candidate migration CLI가 versioned JSON을 생성하고 strict preflight와
   실제 TTS smoke를 통과해야 두 container를 시작합니다.
5. `configuration.json`에 production `runtime`과 실제 사진·일정이 있는지
   확인합니다.

public traffic 전 중간 실패 시 script가 legacy snapshot의 정확한 파일 목록까지
복구하고 이전 release를 검증합니다. snapshot restore나 이전 API·web smoke가
실패하면 maintenance를 유지하므로 수동 조사해야 합니다. 손상된 JSON을
기본값으로 덮어써서는 안 됩니다.

## 3. Host Nginx와 Cloudflare

```bash
sudo install -m 0644 deploy/nginx/reminiscence \
  /etc/nginx/sites-available/reminiscence
sudo ln -sfn /etc/nginx/sites-available/reminiscence \
  /etc/nginx/sites-enabled/reminiscence
sudo nginx -t
sudo systemctl reload nginx
```

기존 Nginx 파일에 같은 `server_name`이 있다면 먼저 백업하고 해당 server block을
제거합니다. `sudo nginx -T` 결과에서
`reminiscence.leehyowon14.dev` server가 정확히 하나인지 확인합니다. API와 web
container port는 `127.0.0.1`에만 열고 host firewall이나 router에 직접
publish하지 않습니다.

Cloudflare Tunnel은 host Nginx의 port 80으로 전달하고 HTTPS를 강제합니다.
`/api/*` cache는 우회해야 합니다. domain 전체 Cloudflare Access는 무인
Tablet cookie 흐름을 차단하므로 사용하지 않습니다.

## 4. CI/CD release

FE `main` workflow가 먼저 성공해 자체 ARM64 image와 품질 게이트를 확인해야 합니다.
그 뒤 BE `main` workflow가 검증한 exact FE source를
`ghcr.io/kw-reminiscence/reminiscence-web-release`로 다시 build해 release digest를
소유합니다. 이 경계는 private GHCR package의 cross-repository token 권한에
의존하지 않습니다. `ENABLE_PRODUCTION_DEPLOY` repository
variable이 `true`가 되기 전까지 push는 검증과 image 게시까지만 수행하며 production
deploy는 시작하지 않습니다.

1. GitHub-hosted runner에서 pytest, Ruff, mypy와 OpenAPI 검증
2. API ARM64 image build·SBOM·provenance 게시
3. FE `main`의 정확한 commit을 현재 BE OpenAPI로 다시 typecheck·build
4. 해당 FE commit과 API image를 release 전용 immutable digest로 게시
5. rpi5의 `reminiscence` label runner에서 두 digest 통합 배포

최초 legacy 전환은 BE image가 게시된 뒤 Actions의 `CI/CD`에서 **Run workflow**를
선택하고 `apply_json_migrations`를 켜서 한 번만 실행합니다. 실제 HTTPS 인수가
끝난 뒤 repository variable `ENABLE_PRODUCTION_DEPLOY=true`를 설정하면 이후 BE
`main` push부터 자동 production deploy가 활성화됩니다. 이 순서를 뒤집어 최초
push가 legacy data에 일반 배포를 시도하게 해서는 안 됩니다.

rpi5 runner는 image pull, snapshot, migration, Compose와 smoke만 수행합니다.
runner 상태는 다음처럼 확인합니다.

```bash
systemctl status \
  actions.runner.KW-Reminiscence-Reminiscence-BE.rpi5-server.service
```

수동 배포도 tag가 아닌 두 digest를 모두 전달해야 합니다.

```bash
./scripts/deploy.sh production \
  ghcr.io/kw-reminiscence/reminiscence-be@sha256:<64-hex> \
  ghcr.io/kw-reminiscence/reminiscence-fe@sha256:<64-hex> \
  <BE-40-character-commit> <FE-40-character-commit> <openapi-sha256>
```

schema 변경을 검토하고 승인한 release에서만
`APPLY_JSON_MIGRATIONS=1`을 같은 명령 앞에 둡니다. script는 candidate pull,
web `nginx -t`, API preflight·TTS smoke를 먼저 수행한 뒤 maintenance, API stop,
predeploy snapshot, migration, 두 container 기동과 loopback/public smoke 순서로
진행합니다.

현재 상태는 `release.json`, 이전 상태는 `release.previous.json`,
`.env.previous`, `docker-compose.previous.yml`에 남습니다. release 파일에는
비밀값이 없고 FE·API commit·digest, OpenAPI hash와 predeploy snapshot 경로만
있습니다.

## 5. 자동 backup과 복구 훈련

```bash
sudo install -m 0755 scripts/backup.sh /usr/local/bin/reminiscence-backup
sudo install -m 0755 scripts/restore-drill.sh \
  /usr/local/bin/reminiscence-restore-drill
sudo install -m 0644 deploy/systemd/reminiscence-backup.service \
  deploy/systemd/reminiscence-backup.timer \
  deploy/systemd/reminiscence-restore-drill.service \
  deploy/systemd/reminiscence-restore-drill.timer \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now \
  reminiscence-backup.timer reminiscence-restore-drill.timer
systemctl list-timers 'reminiscence-*'
```

backup은 KST 03:15에 실행하며 daily 7개, weekly 4개, monthly 6개를 유지합니다.
삭제 전 각 snapshot의 manifest, SHA-256과 JSON schema를 검증합니다. secret과
auth session은 backup에 포함하지 않습니다.

복구 훈련은 매월 1일 KST 04:30에 최신 daily snapshot을 격리 임시 directory로
복구합니다. 제외된 auth JSON은 빈 상태로 migration하고 strict preflight와 실제
Supertonic WAV smoke를 통과한 뒤 임시 directory를 제거합니다. live data는
변경하지 않습니다.

```bash
journalctl -u reminiscence-backup.service -n 100 --no-pager
journalctl -u reminiscence-restore-drill.service -n 100 --no-pager
```

## 6. 장애와 rollback

배포 중 오류가 나면 maintenance를 유지하고 다음 원칙을 적용합니다.

- migration 전 또는 public traffic 전: candidate를 내리고 predeploy snapshot과
  이전 FE·API Compose를 함께 복구
- migration 뒤 public traffic 유입 후: 새 기록 유실 위험 때문에 data와 image를
  자동 rollback하지 않고 maintenance 상태에서 수동 판단
- snapshot restore 자체가 실패: 이전 app을 임의로 시작하지 않고 maintenance
  유지

수동 조사 시 먼저 현재 파일과 container를 보존한 채 다음을 확인합니다.

```bash
docker compose --project-name reminiscence-production \
  --env-file /home/ubuntu/apps/reminiscence/production/.env \
  --file /home/ubuntu/apps/reminiscence/production/docker-compose.yml ps
curl --fail http://127.0.0.1:3010/api/health/ready
curl --fail http://127.0.0.1:3011/healthz
cat /home/ubuntu/apps/reminiscence/production/release.json
```

`application-secrets.json`과 사진 base64는 terminal 출력에 포함하지 않습니다.

## 7. 인수 smoke와 비밀값 교체

실제 HTTPS에서 다음을 확인합니다.

- Tablet pairing → 사진 홈 → 루틴 확인 → 사진 홈
- 정시·자발 대화 → 마이크 녹음 → TTS → 완료 → 사진 홈
- Guardian 오입력·login·새로고침·logout·session 만료
- Guardian 월별 기록과 이상 근거
- `/api/health/live`, `/api/health/ready`
- SMTP 실제 수신

평문 Guardian 비밀번호나 pairing code 변경 시 기존 session이 revoke되는지
확인합니다. host나 log에 노출 가능성이 있었던 API key·Cloudflare credential은
별도 관리 화면에서 rotate하고 새 값을 mode 0600 JSON에 반영한 뒤 재배포합니다.
