# codex-notify 🔔

**codex-notify**는 OpenAI Codex CLI 작업이 완료되었을 때 Telegram으로 알림을 보내주는 편리한 도구입니다.

Codex가 복잡한 코드를 생성하거나 긴 작업을 처리하는 동안 화면만 바라보고 계셨나요? 이제는 다른 업무를 보셔도 됩니다. 작업이 끝나는 순간, 텔레그램이 여러분께 완료 소식을 바로 알려드립니다.

---

## 📑 목차

1. [요구사항](https://www.google.com/search?q=%23%EC%9A%94%EA%B5%AC%EC%82%AC%ED%95%AD)
2. [설치 방법](https://www.google.com/search?q=%23%EC%84%A4%EC%B9%98-%EB%B0%A9%EB%B2%95)
3. [사전 준비: Telegram 봇 만들기](https://www.google.com/search?q=%23%EC%82%AC%EC%A0%84-%EC%A4%80%EB%B9%84-telegram-%EB%B4%87-%EB%A7%8C%EB%93%A4%EA%B8%B0)
4. [사용법](https://www.google.com/search?q=%23%EC%82%AC%EC%9A%A9%EB%B2%95)
5. [동작 원리](https://www.google.com/search?q=%23%EB%8F%99%EC%9E%91-%EC%9B%90%EB%A6%AC)
6. [설정 파일 및 로그](https://www.google.com/search?q=%23%EC%84%A4%EC%A0%95-%ED%8C%8C%EC%9D%BC-%EB%B0%8F-%EB%A1%9C%EA%B7%B8)
7. [문제 해결](https://www.google.com/search?q=%23%EB%AC%B8%EC%A0%9C-%ED%95%B4%EA%B2%B0)

---

## 🛠 요구사항

시작하기 전에 아래 환경이 갖춰져 있는지 확인해 주세요.

* **Python:** 3.9.2 버전 이상
* **OpenAI Codex CLI:** 설치 및 기본 설정 완료 ([공식 저장소](https://github.com/openai/codex))
* **Telegram:** 알림을 받을 계정과 봇

---

## 🚀 설치 방법

현재 GitHub을 통해 직접 설치하실 수 있습니다.

**pip로 설치하기:**

```bash
pip install git+https://github.com/sebastianrcnt/codex-notify

```

**pipx로 설치하기 (권장):**

> 전역 CLI 도구로 관리하기 편리하며 의존성 충돌을 방지합니다.

```bash
pipx install git+https://github.com/sebastianrcnt/codex-notify

```

설치가 완료되면 터미널에서 `codex-notify --help`를 입력해 정상 작동 여부를 확인해 보세요.

---

## 🤖 사전 준비: Telegram 봇 만들기

알림을 보내줄 '비서 봇'을 먼저 만들어야 합니다.

### 1. 봇 토큰 발급받기

1. 텔레그램에서 **[@BotFather](https://t.me/BotFather)**를 찾아 대화를 시작합니다.
2. `/newbot`을 입력하고 안내에 따라 봇 이름과 사용자명(Username)을 정합니다.
3. 생성이 완료되면 `123456789:ABC...` 형태의 **API 토큰**이 발급됩니다. 이 토큰은 외부에 노출되지 않게 잘 보관해 주세요.

### 2. 내 Chat ID 확인하기

봇이 나를 찾을 수 있도록 고유 ID가 필요합니다.

1. **[@userinfobot](https://t.me/userinfobot)**에 접속해 `/start`를 보냅니다.
2. 응답으로 오는 `Id` 항목의 숫자(예: `987654321`)를 메모해 두세요.

---

## 💡 사용법

### 1. 온보딩 (간편 설정)

가장 쉬운 방법입니다. 터미널에 아래 명령어를 입력하면 대화형 가이드가 시작됩니다.

```bash
codex-notify

```

가이드에 따라 **네트워크 접근 허용, 봇 토큰, Chat ID**를 차례로 입력하면 모든 설정이 끝납니다.

### 2. 수동 훅 설치

가이드 없이 바로 설치하고 싶다면 다음 명령어를 사용하세요.

```bash
codex-notify install-hook

```

* **팁:** 기존에 설정한 토큰 정보를 유지하고 싶다면 `--no-overwrite` 옵션을 추가하세요.

### 3. 상태 및 제거

* **설정 확인:** `codex-notify status` (현재 설치 상태와 경로를 한눈에 보여줍니다.)
* **훅 제거:** `codex-notify remove-hook` (설정된 훅과 관련 파일을 깔끔하게 삭제합니다.)

---

## ⚙️ 동작 방식

작동 과정은 아주 심플합니다.

1. **Codex CLI 작업 완료:** 작업이 끝나는 순간 Codex가 이벤트를 발생시킵니다.
2. **훅 실행:** 설정된 `notify-hook.py`가 실행되며 이벤트 데이터를 읽습니다.
3. **알림 전송:** 저장된 토큰을 이용해 텔레그램 API를 호출, 사용자에게 메시지를 보냅니다.

**알림 메시지에는 이런 정보가 담겨요:**

* 작업 요약 (응답 첫 줄)
* 작업이 수행된 폴더 위치 (`folder:`)
* 사용 중인 호스트명 (`host:`) 및 세션 ID (`sid:`)

---

## 📂 설정 파일 및 로그

모든 설정은 `~/.codex/` 폴더 내에서 관리됩니다.

* `config.toml`: Codex CLI의 메인 설정 파일 (네트워크 및 훅 경로 포함)
* `notify-hook-tokens.toml`: 여러분의 텔레그램 봇 토큰과 ID가 담긴 파일
* `log/notify.log`: 알림이 안 올 때 원인을 파악할 수 있는 일기장입니다.

---

## ❓ 문제 해결 (FAQ)

**Q. 알림이 오지 않아요!**

* `codex-notify status`를 입력해 모든 파일이 `exists` 상태인지 확인해 보세요.
* 텔레그램 봇에게 **먼저 메시지**를 보냈는지 확인해 주세요. (봇은 먼저 말을 걸 수 없습니다.)
* `~/.codex/log/notify.log` 파일을 열어 에러 메시지가 있는지 살펴봐 주세요.

**Q. 네트워크 관련 오류가 떠요.**

* Codex 샌드박스 설정에서 외부 통신이 차단되어 있을 수 있습니다. `~/.codex/config.toml`에 `network_access = true`가 제대로 들어있는지 확인해 보세요.

---

**더 궁금한 점이 있거나 도움이 필요하신가요? 언제든 물어봐 주세요!**
