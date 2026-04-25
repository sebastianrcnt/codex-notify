# codex-notify 🔔

Codex CLI의 `notify` 이벤트를 받아 Telegram으로 완료 알림만 전달하는 가벼운 일회성 훅입니다.
Codex CLI → Telegram으로 **단방향**으로만 동작하며, Telegram에서 Codex를 제어하거나 상태 조회를 요청할 수 없습니다.

## 목차

1. [소개](#소개)
2. [설치](#설치)
3. [빠른 시작](#빠른-시작)
4. [명령어](#명령어)
5. [보안](#보안)
6. [진단/상태 확인](#진단상태-확인)
7. [문제 해결](#문제-해결)
8. [주의사항](#주의사항)

## 소개

- 이것이 맞는 용도입니다:  
  Codex CLI 작업 완료 이벤트를 받아 Telegram 알림을 보내는 기능
- 이것이 아닌 용도입니다:  
  Telegram으로 Codex를 원격 제어하거나 상태를 조회하는 브릿지 동작

## 설치

### 필수 조건

- Python 3.9 이상
- OpenAI Codex CLI 설치
- Telegram Bot 토큰
- 대상 채팅/채널 chat_id

### 권장 설치

```bash
pipx install git+https://github.com/sebastianrcnt/codex-notify
```

pipx가 없다면 `pipx`를 먼저 설치하세요.

## 빠른 시작

1. BotFather로 봇 생성 후 토큰 획득
2. 본인 채팅 또는 그룹의 `chat_id` 획득
3. 설치 실행

```bash
codex-notify install
```

4. 저장된 설정으로 테스트 전송

```bash
codex-notify test
```

5. 상태와 진단 점검

```bash
codex-notify status
codex-notify doctor --no-network
```

## 명령어

- `codex-notify`  
  인자가 없으면 대화형 설치(온보딩)를 실행합니다.
- `codex-notify install`  
  훅 파일과 토큰 파일을 설치합니다. 기존 토큰을 덮어쓸지 묻습니다.
- `codex-notify uninstall`  
  설치된 훅을 제거합니다. 토큰 파일은 기본적으로 유지합니다.
- `codex-notify status`  
  설치 경로, 훅 파일 존재 여부, 권한 상태를 출력합니다.
- `codex-notify test`  
  Codex 이벤트 없이 현재 토큰/채팅 설정으로 테스트 메시지를 전송합니다.
- `codex-notify doctor`  
  Python 버전, 설정 경로, 훅/토큰 존재 여부, 권한 상태를 점검하고 네트워크가 허용되면 테스트 메시지를 한 번 전송합니다.
  `--no-network`를 사용하면 전송을 건너뜁니다.
- `codex-notify configure-network --enable|--disable`  
  `~/.codex/config.toml`의 `network_access`를 명시적으로 제어합니다.
- `codex-notify install-hook` (alias)  
  `install`의 별칭
- `codex-notify remove-hook` (alias)  
  `uninstall`의 별칭

## 보안

- 토큰 저장 위치: `~/.codex/notify-hook-tokens.toml`
- 토큰 파일 권한: 설치 시 `0600` 권장/설정
- 메시지 기본 모드는 **짧고 보수적**입니다.
- 기본 메시지는 `마크다운` 파싱을 사용하지 않습니다.
- 긴 본문 전체를 기본으로 포함하지 않으며, `CODEX_NOTIFY_INCLUDE_BODY=1` 또는 토큰 파일의 `[telegram].include_body = true`를 설정할 때만 본문 상세를 포함합니다.
- 알림 전송 전/후 로그는 토큰을 마스킹하고, 로컬 디버그용으로만 보존합니다.
- `network_access`는 기본으로 자동 활성화하지 않습니다. 필요 시 `configure-network --enable`로 명시적으로 설정하세요.

## 진단/상태 확인

- `codex-notify status`
  - `~/.codex/config.toml` 경로
  - 훅/토큰 파일 경로 및 존재 여부
  - 훅 실행/읽기 권한
  - `network_access` 상태
- `codex-notify doctor`
  - 위 항목 + Telegram 테스트 전송(또는 `--no-network` 건너뜀)
  - 토큰/설정 값은 출력하지 않습니다.

## 문제 해결

- 봇이 채널에 먼저 메시지를 보내지 못해 실패: 먼저 봇에게 채팅을 보내두세요.
- `token file permissions are too open` 경고가 뜨면 `chmod 600 ~/.codex/notify-hook-tokens.toml` 실행
- Telegram 전송이 안 되면 `codex-notify doctor`에서 네트워크 상태 확인
- `network_access`가 false라면 필요 시 `codex-notify configure-network --enable`
- `notify`가 Codex 실행마다 호출되지 않으면 `status`/`doctor`로 훅 경로를 점검하고 Codex 설정을 확인하세요.
- 로그 파일: `~/.codex/log/notify.log`

## 주의사항

- 이 도구는 Telegram polling/webhook 서버나 Telegram로부터의 명령 수신을 구현하지 않습니다.
- 설치한 토큰/채팅 정보는 Codex 훅 실행 시점에만 읽히고, 훅 파일 자체에는 임베드하지 않습니다.
