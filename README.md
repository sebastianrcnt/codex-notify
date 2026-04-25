# codex-notify

`codex-notify`는 Codex CLI의 `notify` 이벤트를 Telegram으로 전달하는 **단방향 알림 도구**입니다.

이 프로젝트의 범위:
- Codex CLI notify 이벤트 → Telegram 메시지 전송

이 프로젝트의 범위가 아닌 것:
- Telegram에서 Codex를 원격 조종하는 양방향 브릿지
- Telegram polling/webhook 서버

## 목차

1. [소개](#소개)
2. [요구사항](#요구사항)
3. [설치](#설치)
4. [업데이트](#업데이트)
5. [빠른 시작](#빠른-시작)
6. [명령어](#명령어)
7. [보안 원칙](#보안-원칙)
8. [진단](#진단)
9. [문제 해결](#문제-해결)
10. [제거](#제거)

## 소개

- Codex 작업 완료/이벤트를 Telegram으로 짧게 알림합니다.
- 기본 메시지는 보수적으로 요약해서 전송합니다.
- 긴 본문은 opt-in일 때만 전송합니다.

## 요구사항

- Python 3.9+
- Codex CLI
- Telegram bot token
- Telegram chat id

## 설치

권장:

```bash
uv tool install git+https://github.com/sebastianrcnt/codex-notify
```

대안:

```bash
pipx install git+https://github.com/sebastianrcnt/codex-notify
```

임시 실행:

```bash
uvx --from git+https://github.com/sebastianrcnt/codex-notify codex-notify --help
```

설치 후:

```bash
codex-notify install
codex-notify test
codex-notify doctor
```

## 업데이트

`codex-notify` 업데이트는 두 단계입니다.
1) 도구 버전 업데이트
2) 로컬 안정 경로(`~/.codex/notify-hook.py`)로 hook 갱신

### uv 사용자

```bash
uv tool upgrade codex-notify
codex-notify update
codex-notify test
codex-notify doctor
```

GitHub URL 설치에서 `upgrade`가 애매하면:

```bash
uv tool install --force git+https://github.com/sebastianrcnt/codex-notify
codex-notify update
```

### pipx 사용자

```bash
pipx upgrade codex-notify
codex-notify update
codex-notify test
```

GitHub URL 설치에서 `upgrade`가 동작하지 않으면:

```bash
pipx install --force git+https://github.com/sebastianrcnt/codex-notify
codex-notify update
```

주의:
- `uvx`는 임시/캐시 환경일 수 있습니다.
- Codex notify 설정은 `uvx`/`pipx` 내부 경로를 직접 가리키지 않고, 항상 `~/.codex/notify-hook.py`를 가리키도록 유지해야 합니다.

## 빠른 시작

1. `@BotFather`로 봇 생성 후 token 발급
2. 알림 받을 chat id 확인
3. `codex-notify install`
4. `codex-notify test`
5. `codex-notify doctor --no-network`

## 명령어

- `codex-notify install`
  - hook/config 설치
  - 기존 `~/.codex/notify-hook-tokens.toml`이 있으면 보존
- `codex-notify update`
  - 패키지에 포함된 최신 `notify-hook.py`를 `~/.codex/notify-hook.py`로 갱신
  - `~/.codex/config.toml`의 `notify`를 안정 경로로 정리
  - credential은 변경하지 않음
- `codex-notify reconfigure`
  - Telegram token/chat_id만 재설정
- `codex-notify uninstall`
  - hook/config 제거
  - credential은 기본 유지
  - `--delete-credentials`를 주면 credential도 삭제
- `codex-notify test`
  - 현재 credential로 Telegram 테스트 메시지 전송
- `codex-notify doctor`
  - 진단 전체 실행
  - `--no-network`로 Telegram 네트워크 테스트 생략
- `codex-notify status`
  - 설치 상태/경로/권한 요약
- `codex-notify configure-network --enable|--disable`
  - `~/.codex/config.toml`의 `network_access`를 명시적으로 변경
- alias
  - `codex-notify install-hook` → `install`
  - `codex-notify remove-hook` → `uninstall`

## 보안 원칙

- credential 파일: `~/.codex/notify-hook-tokens.toml`
- credential 파일 권한: `0600` 권장 및 자동 보정 시도
- `~/.codex` 디렉터리 권한: `0700` 권장 및 자동 보정 시도
- `install`/`update`는 credential을 기본적으로 덮어쓰지 않음
- credential 변경은 `reconfigure`에서만
- `status`/`doctor`/로그에 token/chat_id 원문 노출 금지
- 메시지 전송 전 민감 패턴(`sk-`, `ghp_`, `github_pat_`, `xoxb-`, `TOKEN=`, `SECRET=`, `PASSWORD=`, `API_KEY=` 등) 마스킹
- `network_access=true`는 자동으로 켜지지 않음

## 진단

`codex-notify doctor`는 다음을 확인합니다.
- Python version
- Codex config 존재 여부
- notify hook 설치 여부
- hook 파일 존재/권한
- token 파일 존재/권한
- token 로드 가능 여부(마스킹 출력)
- Telegram 테스트 가능 여부 (`--no-network` 제외 시)
- `network_access` 현재 상태
- 로그 파일 위치

## 문제 해결

- Telegram 실패 시:
  - token/chat_id 오입력 여부 확인 (`codex-notify reconfigure`)
  - 봇에 먼저 메시지를 보내야 하는지 확인
  - 네트워크 차단 여부 확인 (`codex-notify doctor`)
- `network_access`가 `false`/`unset`이면 필요 시:
  - `codex-notify configure-network --enable`
- 로그 확인:
  - `~/.codex/log/notify.log`

## 제거

```bash
codex-notify uninstall
```

credential도 함께 삭제하려면:

```bash
codex-notify uninstall --delete-credentials
```
