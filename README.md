# GC메디아이 DART 재무분석 Agent

OpenDART API로 사업보고서 공시 목록과 연간 재무제표를 수집하고 주요 재무비율을 계산합니다. GitHub Actions로 매월 1일 자동 실행하며, `docs/`를 GitHub Pages로 배포해 대시보드로 볼 수 있습니다.

## 포함 기능

- 사업보고서 공시 목록: 설정한 시작 연도(기본 2010년)부터 현재 연도까지 검색
- 표준 재무제표 계정: 연결재무제표(CFS)를 우선 조회하고, 없으면 별도재무제표(OFS) 사용
- 주요 수치: 총자산, 현금및현금성자산, 매출채권, 재고자산, 유동자산, 유형자산, 총부채, 차입금(계정이 반환되는 경우), 유동부채, 자본총계, 매출액, 매출총이익, 매출원가, 판관비, 영업이익, 세전이익, 당기순이익, 영업/투자/재무활동현금흐름, 이자비용, 감가상각비 등
- 주요 비율: 매출증가율, 매출총이익률, 영업이익률, 순이익률, EBITDA 대용치/마진, ROA, ROE, 유동비율, 부채비율, 자기자본비율, 현금/유동부채, 순차입금 대용치, 영업현금흐름/순이익, 이자보상배율
- 저장 결과: `data/raw/`, `reports/`, `docs/data/`
- 대시보드: `docs/index.html`

## 중요: 데이터 범위

사업보고서 공시 목록은 2010년부터 검색하지만, OpenDART 표준 재무제표 API에서 2010년부터 모든 연도의 상세 계정이 제공된다고 보장할 수 없습니다. 구현은 API가 반환한 데이터만 사용하고 누락 연도를 임의로 채우지 않습니다. 과거 연도 재무제표는 DART 원문/첨부 XBRL을 별도로 파싱해야 할 수 있습니다.

## 1. OpenDART API 키 발급

1. https://opendart.fss.or.kr/ 에서 가입/로그인합니다.
2. 인증키 신청 메뉴에서 API 인증키를 발급받습니다.
3. 키를 소스코드, README, 공개 이슈 또는 커밋에 직접 넣지 마세요. GitHub 저장소의 **Settings → Secrets and variables → Actions → New repository secret**에 `DART_API_KEY`라는 이름으로 저장합니다.
4. `DART_CORP_CODE`는 선택 사항입니다. 회사명 자동 검색이 실패하거나 동명 회사가 있으면 정확한 8자리 DART 법인코드를 찾아 같은 방법으로 secret에 등록하세요.

## 2. GitHub 저장소에 업로드

1. ZIP 압축을 풀어 파일/폴더 전체를 `https://github.com/eunjeong1900/ca` 저장소의 `main` 브랜치에 업로드합니다. 기존 파일이 있다면 먼저 확인하고 덮어쓰지 않도록 하세요.
2. 저장소의 **Settings → Secrets and variables → Actions**에서 `DART_API_KEY`를 추가합니다.
3. 저장소의 **Settings → Actions → General → Workflow permissions**에서 워크플로가 저장소에 쓰기 권한을 갖도록 허용합니다(조직 정책상 허용되는 경우).
4. **Actions → Monthly DART update → Run workflow**를 눌러 최초 실행합니다.
5. 로그에서 기업명/법인코드가 정확히 선택되었는지, 재무 데이터 연도가 몇 개 수집되었는지 확인합니다.

## 3. GitHub Pages 대시보드 공개

1. **Settings → Pages**로 이동합니다.
2. Build and deployment의 Source를 **Deploy from a branch**로 선택합니다.
3. Branch는 `main`, folder는 `/docs`로 지정하고 Save를 누릅니다.
4. 배포 완료 후 Pages 설정 화면에 표시되는 사이트 주소로 접속합니다. 주소는 저장소 설정에 따라 달라지므로 임의로 추측하지 마세요.

워크플로는 매월 1일 한국시간 오전 1시 15분에 실행되도록 설정되어 있습니다. GitHub Actions의 예약 실행은 시스템 부하 등에 따라 지연될 수 있습니다. 최초 실행이나 수동 갱신은 Actions에서 `Run workflow`를 이용하세요.

## 4. 로컬 실행(선택)

Python 3.11 이상 권장.

```bash
python -m venv .venv
# Windows PowerShell
.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
$env:DART_API_KEY="발급받은_키"
python scripts/update.py
```

## 산식/주의사항

- 매출증가율 = 당기 매출액 / 전기 매출액 - 1
- 매출총이익률 = 매출총이익 / 매출액 (계정이 없으면 매출액 - 매출원가로 보완)
- 영업이익률 = 영업이익 / 매출액
- 순이익률 = 당기순이익 / 매출액
- 유동비율 = 유동자산 / 유동부채
- 부채비율 = 총부채 / 자본총계
- 자기자본비율 = 자본총계 / 총자산
- ROA = 당기순이익 / 평균 총자산, ROE = 당기순이익 / 평균 자본
- 영업현금흐름/순이익 = CFO / 당기순이익
- 이자보상배율 = 영업이익 / 이자비용
- 순차입금은 차입금 계정이 API에서 식별될 때만 계산하며, 단기/장기 차입금 누락 시 실제 차입금을 과소계상할 수 있습니다.
- 평균자산/평균자본은 직전 연도 값이 있어야 하므로 첫 해 ROA/ROE는 비어 있을 수 있습니다.
- DSO/DIO/DPO/CCC, ROIC-WACC, PER/PBR/EV/EBITDA 등은 매입채무·외상매입액, 투하자본·자본비용, 주가·시가총액 등의 추가 데이터가 필요하므로 현재 자동 계산 대상에서 제외했습니다.
- 연결과 별도 기준을 혼합해 추세를 비교하지 마세요. 데이터에 `fs_div`가 표시됩니다.
