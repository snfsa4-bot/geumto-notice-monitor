# 성남금토 공고 자동 모니터링

기존 금토지구 홈페이지와 별도로 운영할 나라장터·LH 공공조달 모니터링 프로젝트입니다. 이메일은 발송하지 않습니다.

**운영 검증:** 공식 API 8종 전체 조회 및 게시 자료 6건의 공고명·번호·날짜·금액 대조를 통과했습니다.

- 홈페이지: https://snfsa4-bot.github.io/geumto-notice-monitor/
- 매일 오전 9시 한국시간(UTC 00:00)에 자동 조회·게시합니다. GitHub 예약 실행은 지연·누락될 수 있으며 정각 게시를 보장하지 않습니다.
- 검증 결과: [data/verification.json](data/verification.json), [검증 기록](docs/VALIDATION.md).
- 최근 7일 자료 3건과 월 단위 발주계획 3건을 구분합니다. 발주계획 등록일이 지난달이어도 이번 조회월 계획에 포함될 수 있습니다.
- 이메일을 발송하는 코드는 없습니다.

## 사용자 설정

인증키는 Actions Secrets의 `DATA_GO_KR_KEY`로 관리합니다. Pages의 Source는 GitHub Actions입니다.
키를 갱신할 때에는 [Actions Secrets](https://github.com/snfsa4-bot/geumto-notice-monitor/settings/secrets/actions)에서 기존 값을 수정하세요.
수동 조회는 [Actions](https://github.com/snfsa4-bot/geumto-notice-monitor/actions) → ‘금토 공고 수집과 홈페이지 발행’ → Run workflow에서 실행합니다.
일상 조회는 3일을 중복 조회하며, 7일을 선택하면 공식 필드 대조도 실행합니다.
정기 실행은 7일 실검증을 통과한 뒤 워크플로에서 활성화했습니다. 추가 Variables 설정은 필요 없습니다.
사이트는 마지막 조회가 27시간을 넘으면 지연 상태를 표시합니다.

## 동작과 한계

- XML·JSON 오류, 인증키 미설정, 통신 실패, 반복 페이지·건수 불일치를 ‘신규 공고 없음’으로 처리하지 않습니다.
- 조회 실패에도 상태를 사이트에 반영한 뒤 Actions 작업을 실패로 표시합니다. 실행 기록과 상태 아티팩트로 확인하며 이메일 발송 코드는 없습니다.
- 과거 3일을 중복 조회하고, 최초확인과 이번 확인을 구분하며 변경 이력을 보존합니다.
- 공고 제목·사업 필드의 성남금토 연관성을 확인합니다. A-4BL만 있는 타지역 자료를 게시하지 않습니다.
- 금토1·금토2·A-4BL·기반시설과 단계·확인기간을 필터링합니다. 미분류 공고를 금토1로 추정하지 않습니다.
- 기초금액·예산·계약금액 등 금액 종류를 유지합니다. 개찰 결과를 최종낙찰로 표시하지 않습니다.
- 상세 URL이 없으면 ‘공식 사이트 검색’으로 안내합니다.
- LH 계약은 계약번호를 비워 두는 기간 전체조회가 실검증됐습니다.
- 교차기관 중복은 공고번호·차수·기관·단계가 일치할 때만 묶으며, 명시된 참조번호로만 단계를 연결합니다.
- 약한 지역근거 자료는 공개하지 않습니다. 별도의 관리자 검토 화면은 아직 제공하지 않습니다.
- 변경 감지는 조회 범위 내 같은 공고의 원자료 비교를 기반으로 합니다. 오래된 공고의 변경은 API 검색 범위에 다시 포함돼야 탐지할 수 있습니다.

## 개발 검증

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m app.render
node --check site/assets/app.js
```

`python -m app.collector --days 7`은 환경변수 `DATA_GO_KR_KEY`를 이용합니다.
`REQUIRE_COMPLETE_RUN=1`이면 필수 항목 중 하나라도 실패할 때 종료코드 2를 반환하되 조회 상태는 먼저 저장합니다.
