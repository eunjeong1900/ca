from __future__ import annotations
import io, json, os, re, sys, zipfile
from datetime import datetime, timezone
from pathlib import Path
import requests
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
REPORTS = ROOT / 'reports'
WEB_DATA = ROOT / 'docs' / 'data'
for p in (RAW, REPORTS, WEB_DATA): p.mkdir(parents=True, exist_ok=True)
API = 'https://opendart.fss.or.kr/api'
KEY = os.getenv('DART_API_KEY', '').strip()
COMPANY_NAME = os.getenv('COMPANY_NAME', 'GC메디아이').strip()
START_YEAR = int(os.getenv('START_YEAR', '2010'))
END_YEAR = int(os.getenv('END_YEAR') or datetime.now().year)
CORP_CODE_OVERRIDE = os.getenv('DART_CORP_CODE', '').strip()
TIMEOUT = 45

if not KEY or KEY == '여기에_발급받은_API_키':
    print('ERROR: DART_API_KEY 환경변수가 없습니다. GitHub Secrets 또는 .env에서 설정하세요.', file=sys.stderr)
    sys.exit(2)

session = requests.Session()
session.headers.update({'User-Agent': 'GC-MediAI-DART-Financial-Agent/1.0'})

def get_json(endpoint, params):
    r = session.get(f'{API}/{endpoint}', params={'crtfc_key': KEY, **params}, timeout=TIMEOUT)
    r.raise_for_status()
    try: data = r.json()
    except ValueError: raise RuntimeError(f'{endpoint}: JSON이 아닌 응답을 받았습니다. API 키와 요청 제한을 확인하세요.')
    status = str(data.get('status', ''))
    if status not in ('000', '013'):
        raise RuntimeError(f'{endpoint} API 오류 status={status}, message={data.get("message", "")}; params={params}')
    return data

def normalize(s):
    return re.sub(r'[^0-9a-z가-힣]', '', str(s).lower())

def get_corp_code():
    if CORP_CODE_OVERRIDE:
        return CORP_CODE_OVERRIDE, COMPANY_NAME
    cache = RAW / 'corpCode.xml'
    # Refresh official company-code list each run; do not persist API key in URL/logs.
    r = session.get(f'{API}/corpCode.xml', params={'crtfc_key': KEY}, timeout=TIMEOUT)
    r.raise_for_status()
    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xml_name = next(n for n in z.namelist() if n.lower().endswith('.xml'))
        xml = z.read(xml_name)
    except Exception as e:
        raise RuntimeError('법인코드 목록을 읽지 못했습니다. OpenDART 인증키가 유효한지 확인하세요.') from e
    cache.write_bytes(xml)
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml)
    rows=[]
    target=normalize(COMPANY_NAME)
    for item in root.findall('.//list'):
        name=(item.findtext('corp_name') or '').strip()
        code=(item.findtext('corp_code') or '').strip()
        stock=(item.findtext('stock_code') or '').strip()
        if name and code: rows.append((name,code,stock))
    exact=[x for x in rows if normalize(x[0]) == target]
    matches=exact or [x for x in rows if target in normalize(x[0]) or normalize(x[0]) in target]
    if not matches:
        suggestions=sorted(rows, key=lambda x: (0 if '메디아이' in x[0] else 1, x[0]))
        suggestions=[x for x in suggestions if '메디아이' in x[0] or 'GC' in x[0]][:20]
        raise RuntimeError(f'회사명 "{COMPANY_NAME}"을 법인코드 목록에서 찾지 못했습니다. DART_CORP_CODE를 설정하세요. 유사 후보: {suggestions}')
    if len(matches)>1:
        print('회사명 후보:', matches)
        raise RuntimeError('회사명이 여러 개 검색되었습니다. 정확한 법인코드를 DART_CORP_CODE로 지정하세요.')
    return matches[0][1], matches[0][0]

# Korean labels from the supplied practical guide. Matching is tolerant to spaces/punctuation.
ACCOUNT_ALIASES = {
 'total_assets':['자산총계','자산 합계'],
 'cash':['현금및현금성자산','현금 및 현금성자산'],
 'receivables':['매출채권','매출채권및기타채권','매출채권 및 기타채권'],
 'inventory':['재고자산'],
 'current_assets':['유동자산'],
 'ppe':['유형자산'],
 'total_liabilities':['부채총계','부채 합계'],
 'current_liabilities':['유동부채'],
 'short_borrowings':['단기차입금','단기차입부채'],
 'long_borrowings':['장기차입금','장기차입부채','사채'],
 'equity':['자본총계','자본 합계'],
 'revenue':['매출액','수익(매출액)','영업수익'],
 'gross_profit':['매출총이익'],
 'cost_of_sales':['매출원가'],
 'sga':['판매비와관리비','판매비와 일반관리비'],
 'operating_profit':['영업이익','영업이익(손실)'],
 'pretax_profit':['법인세비용차감전순이익','법인세비용차감전순손익'],
 'net_income':['당기순이익','당기순이익(손실)','분기순이익'],
 'parent_net_income':['지배기업의 소유주에게 귀속되는 당기순이익','지배기업 소유주지분 순이익'],
 'cfo':['영업활동현금흐름','영업활동으로 인한 현금흐름'],
 'cfi':['투자활동현금흐름','투자활동으로 인한 현금흐름'],
 'cff':['재무활동현금흐름','재무활동으로 인한 현금흐름'],
 'interest_expense':['이자비용','금융원가'],
 'depreciation':['감가상각비','유형자산감가상각비'],
 'amortization':['무형자산상각비','무형자산 상각비'],
 'accounts_payable':['매입채무','매입채무및기타채무','매입채무 및 기타채무'],
 'eps':['주당순이익','기본주당이익'],
}

def to_num(value):
    if value is None: return None
    s=str(value).strip().replace(',','')
    if s in ('','-','—','N/A'): return None
    if s.startswith('(') and s.endswith(')'): s='-'+s[1:-1]
    try: return float(s)
    except ValueError: return None

def account_value(rows, aliases):
    # Prefer exact account-name match. For duplicate names, prefer the most relevant current-period value.
    wanted={normalize(x) for x in aliases}
    found=[]
    for row in rows:
        nm=normalize(row.get('account_nm',''))
        if nm in wanted:
            value=to_num(row.get('thstrm_amount'))
            if value is not None:
                found.append((0 if nm in wanted else 1, value, row.get('account_nm','')))
    if not found:
        for row in rows:
            nm=normalize(row.get('account_nm',''))
            if any(a in nm for a in wanted):
                value=to_num(row.get('thstrm_amount'))
                if value is not None: found.append((1,value,row.get('account_nm','')))
    return found[0][1] if found else None

def fetch_annual_reports(corp_code, company_name):
    reports=[]
    for year in range(START_YEAR, END_YEAR+1):
        try:
            data=get_json('list.json', {'corp_code':corp_code,'bgn_de':f'{year}0101','end_de':f'{year}1231','pblntf_ty':'A','page_no':1,'page_count':100})
            items=data.get('list',[]) or []
            # Annual report filed in a year usually reports the previous fiscal year.
            annual=[x for x in items if '사업보고서' in (x.get('report_nm') or '') and '첨부' not in (x.get('report_nm') or '')]
            for x in annual:
                reports.append({
                    'company_name':company_name,'corp_code':corp_code,'filing_year':year,
                    'report_nm':x.get('report_nm'),'rcept_no':x.get('rcept_no'),
                    'rcept_dt':x.get('rcept_dt'),'flr_nm':x.get('flr_nm'),
                    'dart_url':f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={x.get("rcept_no")}'
                })
        except Exception as e:
            print(f'WARN: {year}년 공시 목록 수집 실패: {e}')
    return reports

def fetch_financial_year(corp_code, year):
    # OpenDART's standardized full-account financial statement endpoint is generally available for 2015 onward.
    # The report code 11011 is annual business report. Try consolidated first, then separate statements.
    for fs_div in ('CFS','OFS'):
        try:
            data=get_json('fnlttSinglAcntAll.json', {'corp_code':corp_code,'bsns_year':str(year),'reprt_code':'11011','fs_div':fs_div})
            rows=data.get('list',[]) or []
            if rows:
                return rows, fs_div
        except Exception as e:
            print(f'INFO: {year} {fs_div} 재무제표 조회 불가: {e}')
    return [], None

def ratio(n,d):
    return (n/d) if n is not None and d not in (None,0) else None

def main():
    corp_code, company_name = get_corp_code()
    print(f'선택 기업: {company_name} / corp_code={corp_code}; 기간={START_YEAR}-{END_YEAR}')
    (RAW/'company.json').write_text(json.dumps({'company_name':company_name,'corp_code':corp_code,'updated_at':datetime.now(timezone.utc).isoformat()},ensure_ascii=False,indent=2),encoding='utf-8')
    reports=fetch_annual_reports(corp_code, company_name)
    pd.DataFrame(reports).to_csv(REPORTS/'annual_reports.csv',index=False,encoding='utf-8-sig')
    (RAW/'annual_reports.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    # The DART financial statement API's standardized annual account history may not extend to 2010.
    years=range(max(2015,START_YEAR),END_YEAR+1)
    all_rows=[]; annual=[]
    for year in years:
        rows,fs_div=fetch_financial_year(corp_code,year)
        if not rows:
            print(f'INFO: {year}년 표준 재무제표 데이터 없음')
            continue
        (RAW/f'accounts_{year}_{fs_div}.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
        vals={key:account_value(rows,aliases) for key,aliases in ACCOUNT_ALIASES.items()}
        # Prefer CFS if it exists; fs_div recorded for transparent comparisons.
        vals.update({'year':year,'company_name':company_name,'corp_code':corp_code,'fs_div':fs_div,'currency_unit':'KRW as reported by DART'})
        annual.append(vals)
        for row in rows:
            all_rows.append({'year':year,'fs_div':fs_div,**row})
    df=pd.DataFrame(annual).sort_values('year') if annual else pd.DataFrame()
    if not df.empty:
        df['revenue_growth']=df['revenue'].pct_change()
        df['gross_margin']=df.apply(lambda r: ratio(r['gross_profit'],r['revenue']),axis=1)
        # If gross profit is not separately disclosed, derive it only when both revenue and cost are present.
        mask=df['gross_margin'].isna() & df['revenue'].notna() & df['cost_of_sales'].notna()
        df.loc[mask,'gross_margin']=(df.loc[mask,'revenue']-df.loc[mask,'cost_of_sales'])/df.loc[mask,'revenue']
        df['operating_margin']=df.apply(lambda r: ratio(r['operating_profit'],r['revenue']),axis=1)
        df['net_margin']=df.apply(lambda r: ratio(r['net_income'],r['revenue']),axis=1)
        df['current_ratio']=df.apply(lambda r: ratio(r['current_assets'],r['current_liabilities']),axis=1)
        df['debt_to_equity']=df.apply(lambda r: ratio(r['total_liabilities'],r['equity']),axis=1)
        df['equity_ratio']=df.apply(lambda r: ratio(r['equity'],r['total_assets']),axis=1)
        df['cash_to_current_liabilities']=df.apply(lambda r: ratio(r['cash'],r['current_liabilities']),axis=1)
        df['net_debt']=df.apply(lambda r: (r['short_borrowings'] or 0)+(r['long_borrowings'] or 0)- (r['cash'] or 0) if r['short_borrowings'] is not None or r['long_borrowings'] is not None else None,axis=1)
        df['cfo_to_net_income']=df.apply(lambda r: ratio(r['cfo'],r['net_income']),axis=1)
        df['interest_coverage']=df.apply(lambda r: ratio(r['operating_profit'],r['interest_expense']),axis=1)
        df['ebitda_proxy']=df.apply(lambda r: (r['operating_profit'] or 0)+(r['depreciation'] or 0)+(r['amortization'] or 0) if r['operating_profit'] is not None else None,axis=1)
        df['ebitda_margin_proxy']=df.apply(lambda r: ratio(r['ebitda_proxy'],r['revenue']),axis=1)
        df['avg_assets']=df['total_assets'].rolling(2).mean()
        df['avg_equity']=df['equity'].rolling(2).mean()
        df['roa']=df.apply(lambda r: ratio(r['net_income'],r['avg_assets']),axis=1)
        df['roe']=df.apply(lambda r: ratio(r['net_income'],r['avg_equity']),axis=1)
        df.to_csv(REPORTS/'financial_analysis.csv',index=False,encoding='utf-8-sig')
        df.to_csv(WEB_DATA/'financial_analysis.csv',index=False,encoding='utf-8-sig')
        # JSON-safe values, NaN -> null.
        clean=json.loads(df.to_json(orient='records',force_ascii=False))
        payload={'company_name':company_name,'corp_code':corp_code,'updated_at':datetime.now(timezone.utc).isoformat(),'start_year':START_YEAR,'end_year':END_YEAR,'filing_count':len(reports),'financial_year_count':len(clean),'notes':['Standardized financial statement data may be available only from 2015 onward; report-list collection starts at configured START_YEAR.','CFS is preferred when available; otherwise OFS is used. Do not compare mixed bases without review.','EBITDA is a proxy calculated as operating profit + depreciation + amortization only when those accounts are disclosed.','Missing values mean the account was not found or not returned by the API; they are not zero.'],'records':clean}
    else:
        payload={'company_name':company_name,'corp_code':corp_code,'updated_at':datetime.now(timezone.utc).isoformat(),'start_year':START_YEAR,'end_year':END_YEAR,'filing_count':len(reports),'financial_year_count':0,'notes':['No annual financial statement rows were returned. Verify the company code and whether the entity files standardized financial statements.'],'records':[]}
    (WEB_DATA/'financial_summary.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    if all_rows:
        pd.DataFrame(all_rows).to_csv(REPORTS/'financial_accounts_raw.csv',index=False,encoding='utf-8-sig')
    print(f'완료: 사업보고서 {len(reports)}건, 재무 데이터 {len(annual)}개 연도')

if __name__=='__main__': main()
