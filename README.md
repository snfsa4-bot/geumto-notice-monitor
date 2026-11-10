# 성남금토 공고 자동 모니터링

기존 금토지구 홈페이지와 별도로 운영할 나라장터·LH 공공조달 모니터링 프로젝트입니다. 이메일은 발송하지 않습니다.

**현재: 코드 준비·테스트 통과, 실 API 정상수집 및 홈페이지 배포 검증 전입니다.**
최근 실호출에서 API 10(요청 인자 오류), API 01(제공기관 내부 오류)이 관찰됐으며 공고 0건으로 확정하지 않았습니다.
공식 명세와 검증의 구분, 남은 구현·검증 항목은 [검증 기록](docs/VALIDATION.md)에 있습니다.

## 직접 필요한 설정

1. [Actions Secrets](https://github.com/snfsa4-bot/geumto-notice-monitor/settings/secrets/actions)에 재발급 키를 `DATA_GO_KR_KEY`라는 이름으로 등록합니다. 키를 코드·채팅에 쓰지 않습니다.
2. [Pages 설정](https://github.com/snfsa4-bot/geumto-notice-monitor/settings/pages)에서 Source를 **GitHub Actions**로 선택합니다.
3. [Actions](https://github.com/snfsa4-bot/geumto-notice-monitor/actions) → ‘금토 공고 수집과 홈페이지 발행’ → Run workflow, 조회 기간 **7일**로 수동 시험합니다.
4. 8종 API 정상 조회와 공고 원문 대조 후에만 Actions Variables의 `MONITOR_ENABLED`를 `true`로 설정합니다.

정기 작업은 한국시간 오전 9시(UTC 00:00)입니다. GitHub 예약 실행은 지연·누락될 수 있으며 정각 게시를 보장하지 않습니다.
사이트는 마지막 조회가 27시간을 넘으면 지연 상태를 표시합니다. 예약 실행 자체가 누락된 경우 정적 홈페이지는 방문 시 경과시간으로 판단합니다.

## 동작과 한계

- XML·JSON 오류, 인증키 미설정, 통신 실패, 반복 페이지·건수 불일치를 ‘신규 공고 없음’으로 처리하지 않습니다.
- 조회 실패에도 상태를 사이트에 반영한 뒤 Actions 작업을 실패로 표시합니다. 실행 기록과 상태 아티팩트로 확인하며 이메일 발송 코드는 없습니다.
- 과거 3일을 중복 조회하고, 최초확인과 이번 확인을 구분하며 변경 이력을 보존합니다.
- 공고 제목·사업 필드의 성남금토 연관성을 확인합니다. A-4BL만 있는 타지역 자료를 게시하지 않습니다.
- 금토1·금토2·A-4BL·기반시설과 단계·확인기간을 필터링합니다. 미분류 공고를 금토1로 추정하지 않습니다.
- 기초금액·예산·계약금액 등 금액 종류를 유지합니다. 개찰 결과를 최종낙찰로 표시하지 않습니다.
- 상세 URL이 없으면 ‘공식 사이트 검색’으로 안내합니다.
- LH 계약의 기간 전체조회 지원 여부, 교차기관 중복 제거·단계 연계, 약한 지역근거 자료의 관리 검토 기능은 추가 검증·보완 대상입니다.

## 개발 검증

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m app.render
node --check site/assets/app.js
```

`python -m app.collector --days 7`은 환경변수 `DATA_GO_KR_KEY`를 이용합니다.
`REQUIRE_COMPLETE_RUN=1`이면 필수 항목 중 하나라도 실패할 때 종료코드 2를 반환하되 조회 상태는 먼저 저장합니다.
