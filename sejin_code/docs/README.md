# docs/ — 문서 지도

CloudChaser 문서가 어디에 있고 **언제 무엇을 보면 되는지** 한눈에 정리한 입구.
"이거 어느 문서 봐야 하지?" 싶으면 여기부터.

## 목적별 라우팅

| 하고 싶은 것 | 볼 문서 | 한 줄 설명 |
|---|---|---|
| 프로젝트가 뭔지·설치·구조·CLI 개요 | [`../README.md`](../README.md) | 첫 페이지 (개요/설치/실행) |
| **실제 측정** (절차·이유·언제·왜) | [`SESSION.md`](SESSION.md) | 측정 매뉴얼 — 살아있는 문서 |
| 세션에서 **명령 복붙** (무엇을 친다) | [`COMMANDS.md`](COMMANDS.md) | 커맨드 사전 + 레지스터/필드 표(부록 A·B) |
| 개발/커밋/코드 규칙 | [`../CLAUDE.md`](../CLAUDE.md) | Claude·개발자용 규칙 |
| 실험 PC ↔ 개발 PC 공유 자료 | [`../reference/README.md`](../reference/README.md) | git 공유 참고자료 폴더 안내 |

## 우리 문서 (살아있는 문서 — 코드 바뀌면 갱신)

- **`SESSION.md`** — 측정 매뉴얼. 전원→bring-up→계측기→측정 절차와 측정 항목별 사용법.
- **`COMMANDS.md`** — 인터랙티브 세션에서 손으로 칠 명령 모음 + 전체 레지스터/필드 표.
- **`README.md`**(이 파일) — 문서 지도.

> SESSION = **왜·언제·어떻게**(절차), COMMANDS = **무엇을 친다**(명령 사전). 둘은 짝.

## vendor 원본 (Sivers 배포물 — 우리 코드 아님, 건드리지 말 것)

- **`sivers_unified_api_v0.1.0/`** — Sivers Unified API 원본 패키지.
  `getting_started.md`(설치) · `cloudchaser_setups.md`(예제) · `register_maps/`(xlsx) · `whl/`(설치 wheel).
- **`Cloudchaser_drv-v1.0.0/`** — Sivers 드라이버/WinCLI 원본 배포물.

> 이전엔 위 vendor md가 `docs/` 최상단에도 복사돼 있었지만(중복), 원본 패키지 폴더 안의 것만 남겼다.

## 레지스터 맵

- **`register_maps/Cloudchaser_Stampede_register_map.xlsx`** — 코드가 참조하는 레지스터/필드 맵.
  (`src/cloudchaser/board/bringup.py`, `scripts/dump_register_map.py` 기준. COMMANDS.md 부록 표의 원본.)

## 개발 산출물 (작업 기록 — 참고용)

- **`superpowers/plans/`, `superpowers/specs/`** — 기능 작업 계획·설계 노트(날짜별).
