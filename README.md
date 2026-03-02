# codex-notify

OpenAI Codex CLI 작업이 완료됐을 때 Telegram으로 알림을 보내주는 훅(hook) 도구입니다.

Codex가 긴 작업을 처리하는 동안 다른 일을 하다가, 완료되면 즉시 알림을 받을 수 있습니다.

---

## 목차

1. [요구사항](#요구사항)
2. [설치](#설치)
3. [사전 준비: Telegram 봇 만들기](#사전-준비-telegram-봇-만들기)
4. [사용법](#사용법)
   - [온보딩 (최초 설정)](#온보딩-최초-설정)
   - [훅 설치](#훅-설치)
   - [훅 제거](#훅-제거)
   - [상태 확인](#상태-확인)
5. [동작 방식](#동작-방식)
6. [설정 파일 구조](#설정-파일-구조)
7. [로그 확인](#로그-확인)
8. [문제 해결](#문제-해결)

---

## 요구사항

- Python 3.9.2 이상
- [OpenAI Codex CLI](https://github.com/openai/codex) 설치 및 설정 완료
- Telegram 계정 및 봇

---

## 설치

> 현재는 GitHub에서 직접 설치하는 방식만 지원합니다.

**pip 사용:**

```bash
pip install git+https://github.com/sebastianrcnt/codex-notify
```

**pipx 사용 (권장 — 전역 CLI 도구에 적합):**

```bash
pipx install git+https://github.com/sebastianrcnt/codex-notify
```

설치 후 `codex-notify` 명령어를 사용할 수 있습니다.

```bash
codex-notify --help
```

---

## 사전 준비: Telegram 봇 만들기

훅을 설치하기 전에 Telegram 봇 토큰과 chat ID가 필요합니다.

### 1. 봇 토큰 발급

1. Telegram에서 **[@BotFather](https://t.me/BotFather)** 를 검색해 대화를 시작합니다.
2. `/newbot` 명령어를 입력합니다.
3. 봇 이름(예: `My Codex Notifier`)과 사용자명(예: `my_codex_bot`)을 순서대로 입력합니다.
4. BotFather가 **봇 토큰**을 발급합니다. 아래와 같은 형식입니다:
   ```
   123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
   ```
   이 토큰을 안전하게 보관하세요.

### 2. Chat ID 확인

알림을 받을 본인의 chat ID를 확인합니다.

1. Telegram에서 **[@userinfobot](https://t.me/userinfobot)** 를 검색해 `/start`를 입력합니다.
2. 봇이 응답한 메시지에서 `Id` 항목의 숫자를 복사합니다.
   ```
   Id: 987654321
   ```

> 그룹/채널로 알림을 받으려면 해당 그룹/채널에 봇을 초대한 뒤, chat ID를 확인합니다. 그룹 chat ID는 보통 `-100`으로 시작하는 음수입니다.

---

## 사용법

### 온보딩 (최초 설정)

처음 사용하는 경우 `codex-notify`를 인수 없이 실행하면 대화형 온보딩이 시작됩니다.

```bash
codex-notify
```

온보딩은 다음 순서로 진행됩니다:

1. **네트워크 접근 설정 확인** — Codex의 샌드박스에서 Telegram API 호출이 가능하도록 `~/.codex/config.toml`에 `network_access = true`를 추가할지 묻습니다.
2. **알림 드라이버 선택** — 현재는 Telegram만 지원합니다.
3. **훅 설치 여부 확인** — `~/.codex/`에 훅 파일을 바로 설치합니다.
4. **Telegram 인증 정보 입력** — 봇 토큰과 chat ID를 입력합니다.

### 훅 설치

온보딩을 건너뛰고 바로 훅을 설치하려면:

```bash
codex-notify install-hook
```

실행하면 다음을 순서대로 처리합니다:

1. `~/.codex/config.toml`에 네트워크 접근 설정 추가 (필요 시 확인 후 추가)
2. Telegram 봇 토큰 및 chat ID 입력 요청
3. 훅 스크립트를 `~/.codex/notify-hook.py`에 복사
4. 인증 정보를 `~/.codex/notify-hook-tokens.toml`에 저장
5. `~/.codex/config.toml`에 `notify` 설정 추가

**기존 토큰 파일을 유지하면서 훅만 재설치하려면:**

```bash
codex-notify install-hook --no-overwrite
```

`--no-overwrite` 옵션을 사용하면 `notify-hook-tokens.toml`이 이미 있는 경우 덮어쓰지 않습니다.

### 훅 제거

```bash
codex-notify remove-hook
```

다음 파일과 설정을 제거합니다:

- `~/.codex/notify-hook.py` 삭제
- `~/.codex/notify-hook-tokens.toml` 삭제
- `~/.codex/config.toml`에서 `notify` 설정 제거

### 상태 확인

현재 설치 상태를 확인하려면:

```bash
codex-notify status
```

출력 예시:

```
Config file: /Users/yourname/.codex/config.toml (exists)
Notify configured: yes
Sandbox network_access: true
Hook script: /Users/yourname/.codex/notify-hook.py (file)
Tokens file: /Users/yourname/.codex/notify-hook-tokens.toml (file)
```

---

## 동작 방식

```
Codex CLI 작업 완료
        ↓
  notify 훅 실행
        ↓
  notify-hook.py 가 JSON 페이로드 수신
        ↓
  ~/.codex/notify-hook-tokens.toml 에서 토큰 로드
        ↓
  Telegram Bot API 호출
        ↓
  사용자 Telegram으로 알림 전송
```

Codex CLI는 작업이 끝나면 `~/.codex/config.toml`에 등록된 `notify` 커맨드를 실행합니다. `codex-notify`는 이 커맨드를 `notify-hook.py`로 설정하며, 훅은 Codex가 전달하는 JSON 이벤트를 파싱해 Telegram 메시지를 생성하고 전송합니다.

현재 지원하는 이벤트:

| 이벤트 타입 | 설명 |
|---|---|
| `agent-turn-complete` | Codex 에이전트 턴 완료 시 요약 알림 전송 |

Telegram 메시지에는 다음 정보가 포함됩니다:

- 작업 요약 (첫 번째 응답 줄 기반)
- 현재 폴더명 (`folder:`)
- 호스트명 (`host:`)
- 세션 ID (`sid:`)

---

## 설정 파일 구조

훅 설치 후 관련 파일들은 다음 위치에 생성됩니다:

```
~/.codex/
├── config.toml                  # Codex CLI 설정 (notify 항목 추가됨)
├── notify-hook.py               # 훅 스크립트 (자동 복사)
├── notify-hook-tokens.toml      # Telegram 인증 정보
└── log/
    └── notify.log               # 훅 실행 로그
```

**`~/.codex/config.toml` 변경 내용:**

```toml
notify = ['python3', '~/.codex/notify-hook.py']

[sandbox_workspace_write]
network_access = true
```

**`~/.codex/notify-hook-tokens.toml` 형식:**

```toml
# 알림 드라이버 선택 (현재 telegram만 지원)
driver = 'telegram'

[telegram]
# @BotFather에서 발급받은 봇 토큰
token = '123456789:ABCdefGHIjklMNOpqrSTUvwxYZ'
# 알림을 받을 chat ID
chat_id = '987654321'
```

---

## 로그 확인

훅 실행 로그는 `~/.codex/log/notify.log`에 기록됩니다.

```bash
tail -f ~/.codex/log/notify.log
```

정상 실행 시:

```
[2026-03-02 14:30:00] === start ===
[2026-03-02 14:30:01] OK 200
[2026-03-02 14:30:01] === done ===
```

오류 발생 시:

```
[2026-03-02 14:30:00] === start ===
[2026-03-02 14:30:00] ERROR: Missing: /Users/yourname/.codex/notify-hook-tokens.toml
```

---

## 문제 해결

**알림이 오지 않는 경우**

1. `codex-notify status`로 설정 상태를 확인합니다.
2. `~/.codex/log/notify.log`에서 오류 메시지를 확인합니다.
3. `~/.codex/config.toml`에 `network_access = true`가 설정되어 있는지 확인합니다.
4. 봇 토큰과 chat ID가 올바른지 확인합니다.

**Telegram 봇이 응답하지 않는 경우**

- 봇에게 먼저 메시지를 보내야 합니다. 봇과 대화를 시작하지 않으면 봇이 먼저 메시지를 보낼 수 없습니다.
- `@BotFather`에서 발급받은 토큰을 정확히 입력했는지 확인합니다.

**`network_access` 관련 오류**

Codex 샌드박스에서 외부 네트워크 접근이 차단된 경우 훅이 실행되더라도 Telegram API 호출에 실패합니다. `~/.codex/config.toml`을 직접 수정해 확인하세요:

```toml
[sandbox_workspace_write]
network_access = true
```

**훅을 재설치하고 싶은 경우**

토큰 설정은 유지하면서 훅 스크립트만 최신 버전으로 업데이트하려면:

```bash
pip install --upgrade git+https://github.com/sebastianrcnt/codex-notify
codex-notify install-hook --no-overwrite
```
