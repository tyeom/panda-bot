# Panda Claude Agent <img width="50" height="50" alt="image" src="https://github.com/user-attachments/assets/7bf2af5f-befc-4d35-bc94-f32cbdd457ac" />


Claude AI 기반 멀티 메신저 봇 플랫폼. Telegram과 Discord를 지원하며, 웹 브라우징, 파일 관리, 프로그램 실행, 작업 스케줄링 기능을 제공합니다.

## 주요 기능

- **멀티 메신저** - Telegram, Discord 동시 지원 (어댑터 패턴으로 확장 가능)
- **듀얼 AI 백엔드** - Anthropic API 직접 호출 또는 Claude Code CLI 중 선택
- **웹 브라우징** - Playwright 기반 웹 스크래핑, 스크린샷, JS 실행
- **파일 시스템** - 디렉토리 탐색, 파일 읽기, 파일 검색
- **프로그램 실행** - 쉘 커맨드 및 스크립트 실행
- **작업 스케줄러** - cron 또는 일회성 예약 작업 (AI가 실행 후 결과를 채팅방에 전송)
- **대화 기록** - SQLite + FTS5 전문 검색, 봇별/세션별 격리
- **멀티 봇** - 하나의 프로세스에서 여러 봇 동시 운영

## 프로젝트 구조

```
src/panda_bot/
├── __main__.py          # CLI 진입점
├── app.py               # 앱 오케스트레이터
├── config.py            # Pydantic 설정 모델 + YAML 로더
├── log.py               # structlog 기반 로깅
├── ai/
│   ├── client.py        # AIClient ABC, AnthropicClient, ClaudeCodeClient
│   ├── conversation.py  # 대화 기록 → 메시지 변환
│   ├── handler.py       # 메시지 처리 핸들러 (도구 루프 포함)
│   ├── tool_runner.py   # Anthropic API용 도구 실행 루프
│   └── tools/
│       ├── base.py      # Tool ABC
│       ├── registry.py  # 도구 등록/검색
│       ├── browser.py   # 웹 브라우징 도구
│       ├── filesystem.py # 파일 시스템 도구
│       ├── executor.py  # 프로그램 실행 도구
│       └── scheduler.py # 스케줄러 도구
├── core/
│   ├── bot_registry.py  # 실행 중인 봇 어댑터 관리
│   ├── session.py       # 봇별/채팅별 세션 관리
│   └── types.py         # 공통 타입
├── messenger/
│   ├── base.py          # MessengerAdapter ABC
│   ├── models.py        # IncomingMessage, OutgoingMessage
│   ├── telegram.py      # Telegram 어댑터
│   └── discord_adapter.py # Discord 어댑터
├── services/
│   ├── base.py          # Service ABC
│   ├── browser.py       # Playwright 브라우저 서비스
│   ├── scheduler.py     # APScheduler 스케줄러 서비스
│   ├── mcp_manager.py   # MCP 서버 관리 (설치/제거/영속화)
│   └── service_manager.py # 서비스 라이프사이클 관리
└── storage/
    ├── database.py      # aiosqlite 래퍼
    ├── models.py        # ConversationRecord 모델
    └── conversation_repo.py # 대화 저장/검색 리포지토리
```

## 빠른 시작

### 요구 사항

- Python 3.11+
- Claude Code CLI (`npm install -g @anthropic-ai/claude-code`) 또는 Anthropic API 키
- Telegram Bot Token 또는 Discord Bot Token

### 설치

```bash
# 자동 설치 (가상환경 생성 + 의존성 + Playwright 브라우저)
python install.py

# 또는 수동 설치
pip install -e .
python -m playwright install chromium
```

### 환경 변수 설정

`.env.example`을 `.env`로 복사하고 값을 채웁니다:

```bash
cp .env.example .env
```

```env
ANTHROPIC_API_KEY=sk-ant-xxxxx        # anthropic 백엔드 사용 시
TELEGRAM_BOT_TOKEN=123456:ABC-DEF     # Telegram 봇
DISCORD_BOT_TOKEN=your-token          # Discord 봇
NATE_MAIL_ID=xxx                      # 선택: 네이트 메일 자동화용
NATE_MAIL_PASSWORD=xxx                # 선택: 네이트 메일 자동화용
```

### 설정 파일

`config.example.yaml`을 `config.yaml`로 복사하고 수정합니다:

```bash
cp config.example.yaml config.yaml
```

### 실행

```bash
# 봇 시작
python -m panda_bot

# 설정 검증
python -m panda_bot config-check

# AI 모델 정보 확인
python -m panda_bot model-info
```

## config.yaml 설정

### AI 백엔드 선택

봇별로 AI 백엔드를 선택할 수 있습니다:

```yaml
bots:
  - id: my-bot
    platform: telegram          # "telegram" | "discord"
    token: ${TELEGRAM_BOT_TOKEN}
    ai:
      backend: claude_code      # "anthropic" | "claude_code"
```

| 백엔드 | 설명 | 요구 사항 |
|--------|------|-----------|
| `anthropic` | Anthropic API 직접 호출 | API 키 + 크레딧 |
| `claude_code` | Claude Code CLI 서브프로세스 | `claude` CLI 설치 + 구독 |

### tools - 봇이 사용할 panda-bot 내장 도구

AI가 대화 중 호출할 수 있는 panda-bot 내장 도구 목록입니다:

```yaml
ai:
  tools:
    - browser       # 웹 브라우징 (Playwright)
    - filesystem    # 파일 시스템 탐색
    - executor      # 프로그램/스크립트 실행
    - scheduler     # 작업 예약 (cron, 일회성)
```

| 도구 | 기능 |
|------|------|
| `browser` | URL 접속, 텍스트/HTML 추출, 스크린샷, JS 실행, 요소 클릭 |
| `filesystem` | 디렉토리 목록, 파일 읽기, 파일 정보, 이름 패턴 검색 |
| `executor` | 쉘 커맨드 및 스크립트 파일 실행 |
| `scheduler` | cron/일회성 AI 작업 예약, 작업 목록 조회, 작업 삭제 |

### model - Claude Code CLI 모델 선택

`claude_code` 백엔드에서 사용할 모델을 지정합니다. 기본값은 `sonnet`입니다:

```yaml
claude_code:
  model: sonnet    # "sonnet" | "opus" | "haiku"
```

| 모델 | 특징 |
|------|------|
| `sonnet` | 균형 잡힌 성능과 속도 (기본값, 권장) |
| `opus` | 최고 성능, 느리고 한도 소모가 큼 |
| `haiku` | 빠르고 가벼움, 단순 작업에 적합 |

### allowed_tools - Claude Code CLI 자체 도구 권한

`claude_code` 백엔드 사용 시, Claude Code CLI가 자체적으로 사용할 수 있는 도구의 권한을 설정합니다. panda-bot의 `tools`와는 별개입니다:

```yaml
claude_code:
  cli_path: claude
  model: sonnet
  timeout: 300
  allowed_tools:
    - "WebFetch"      # 웹 페이지 가져오기
    - "WebSearch"     # 웹 검색
    - "Bash"          # 쉘 커맨드 실행
    - "Read"          # 파일 읽기
    - "Write"         # 파일 쓰기
    - "Edit"          # 파일 편집
    - "Glob"          # 파일 패턴 검색
    - "Grep"          # 파일 내용 검색
```

### 전체 설정 예시

```yaml
log_level: INFO
data_dir: ./data

bots:
  - id: panda-telegram
    platform: telegram
    token: ${TELEGRAM_BOT_TOKEN}
    ai:
      backend: claude_code
      max_tokens: 4096
      system_prompt: |
        You are Panda, a helpful personal assistant bot.
      temperature: 0.7
      tools:
        - browser
        - filesystem
        - executor
        - scheduler

anthropic:
  api_key: ${ANTHROPIC_API_KEY}
  max_retries: 3
  timeout: 120

claude_code:
  cli_path: claude
  model: sonnet
  timeout: 300
  allowed_tools:
    - "WebFetch"
    - "WebSearch"
    - "Bash"

services:
  browser:
    headless: true
    browser_type: chromium
    timeout_ms: 30000
  scheduler:
    timezone: UTC
    max_concurrent_jobs: 5

storage:
  db_path: ${data_dir}/panda_bot.db
  fts_enabled: true
```

## 동작 워크플로우

### 일반 대화 흐름

```
사용자 (Telegram/Discord)
  ↓ 메시지
MessengerAdapter → MessageHandler
  ↓
SessionManager: 세션 ID 조회/생성
  ↓
ConversationRepo: 사용자 메시지 저장 + 대화 기록 로드
  ↓
AIClient.chat(): Claude에게 전송
  ↓
도구 호출이 있으면 → 도구 실행 → 결과와 함께 재전송 (반복, 최대 10회)
  ↓
최종 응답 텍스트
  ↓
MessengerAdapter: 채팅방에 응답 전송
```

### AI 백엔드별 도구 실행

**Anthropic API (`backend: anthropic`)**
- API가 `tool_use` 블록을 반환하면 `tool_runner.py`가 도구를 실행하고 결과를 재전송

**Claude Code CLI (`backend: claude_code`)**
- 시스템 프롬프트에 도구 설명을 추가
- Claude가 `<tool_call>{"tool": "browser", "input": {...}}</tool_call>` 형식으로 출력
- `handler.py`가 파싱하여 도구 실행 후 결과를 다음 메시지로 전달

### 스케줄러 프로액티브 메시징

```
사용자: "5분마다 메일 확인해줘"
  ↓
Claude가 scheduler 도구 호출:
  action: add_cron, cron_expr: "*/5 * * * *", task_prompt: "메일 확인..."
  ↓
5분마다 SchedulerService._run_ai_task() 실행:
  1. ai_client_factory(bot_id) → AI 클라이언트 생성
  2. task_prompt로 AI 호출 (도구 루프 포함)
  3. 브라우저 도구로 메일 사이트 접속/스크래핑
  4. AI가 결과 요약
  5. bot_registry.get(bot_id) → adapter.send_message() → 채팅방에 전송
```

### CLI 명령어

| 명령어 | 설명 |
|--------|------|
| `python -m panda_bot` | 봇 시작 (기본) |
| `python -m panda_bot start` | 봇 시작 |
| `python -m panda_bot config-check` | 설정 파일 검증 |
| `python -m panda_bot model-info` | 봇별 AI 모델 정보 확인 |

### 채팅 명령어

| 명령어 | 설명 |
|--------|------|
| `/reset` | 현재 세션 초기화 (대화 기록 리셋) |
| `/model` | 현재 봇의 AI 백엔드, 모델, 도구 정보 확인 |
| `/search <query>` | 대화 기록 전문 검색 |
| `/stop` | 현재 작업중인 tool 중지 |
| `/mcp list` | 등록된 MCP 서버 목록 확인 |
| `/mcp add <name> <package> [-e KEY=VAL ...]` | 외부 MCP 서버 추가 |
| `/mcp remove <name>` | MCP 서버 제거 |
| `/restart` | 봇 재시작(채팅으로 환경구성 재구성 요청 이후 재시작시 바로 반영) |

## 기술 스택

| 구성 요소 | 기술 |
|-----------|------|
| 언어 | Python 3.11+ |
| AI | Anthropic SDK / Claude Code CLI |
| Telegram | python-telegram-bot |
| Discord | discord.py |
| 브라우저 자동화 | Playwright (Chromium) |
| 스케줄러 | APScheduler |
| 데이터베이스 | aiosqlite (SQLite + FTS5) |
| 설정 검증 | Pydantic v2 |
| 로깅 | structlog |
