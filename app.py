from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from html import unescape
from urllib.parse import urlparse
import os, re, statistics, requests, traceback

app = FastAPI(title="공매가 AI 8.4.2차")
templates = Jinja2Templates(directory="templates")

SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "none").lower()
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "message": f"서버 처리 오류: {type(exc).__name__}: {str(exc)}",
            "error_type": type(exc).__name__,
        },
    )

class Vehicle(BaseModel):
    car: str
    year: int
    km: int
    accident_count: int = 0
    accident_amount: float = 0
    parts_amount: float = 0
    uninsured: int = 0
    use_history: float = 0
    frame: int = 0
    condition: int = 0
    liquidity: int = 0
    special: int = 0
    manual_prices: Optional[List[float]] = None

def clean_text(s) -> str:
    if s is None:
        return ""
    if not isinstance(s, str):
        try:
            s = str(s)
        except Exception:
            return ""
    s = unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def domain_of(url) -> str:
    try:
        if not isinstance(url, str):
            url = "" if url is None else str(url)
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""

def search_web(query: str) -> List[Dict[str, str]]:
    results = []
    if SEARCH_PROVIDER == "brave" and BRAVE_API_KEY:
        r = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY},
            params={"q": query, "count": 20, "country": "kr", "search_lang": "ko"},
            timeout=6,
        )
        r.raise_for_status()
        for x in r.json().get("web", {}).get("results", []):
            results.append({
                "title": clean_text(x.get("title", "")),
                "url": x.get("url", ""),
                "description": clean_text(x.get("description", "")),
                "query": query,
            })
    elif SEARCH_PROVIDER == "serpapi" and SERPAPI_KEY:
        r = requests.get(
            "https://serpapi.com/search.json",
            params={"engine":"google","q":query,"hl":"ko","gl":"kr","api_key":SERPAPI_KEY,"num":20},
            timeout=6,
        )
        r.raise_for_status()
        for x in r.json().get("organic_results", []):
            results.append({
                "title": clean_text(x.get("title", "")),
                "url": x.get("link", ""),
                "description": clean_text(x.get("snippet", "")),
                "query": query,
            })
    return results

def dedupe_results(results):
    seen, out = set(), []
    for x in (results or []):
        if not isinstance(x, dict):
            continue
        raw_url = x.get("url") or ""
        if not isinstance(raw_url, str):
            raw_url = str(raw_url)
        url = raw_url.split("#")[0].rstrip("/")
        title = clean_text(x.get("title", ""))
        key = url or title
        if not key or key in seen:
            continue
        seen.add(key)
        y = dict(x)
        y["title"] = title
        y["description"] = clean_text(x.get("description", ""))
        y["url"] = url
        y["domain"] = domain_of(url)
        out.append(y)
    return out

def build_queries(v):
    km_man = max(1, round(v.km / 10000))
    c = v.car.strip()
    return [
        f'"{c}" {v.year} {km_man}만km 중고차 매물',
        f'{v.year}년식 "{c}" {km_man}만km 판매가',
        f'site:encar.com {v.year} "{c}" {km_man}만km',
        f'site:kbchachacha.com {v.year} "{c}" {km_man}만km',
        f'site:kcar.com {v.year} "{c}" {km_man}만km',
    ]

def relaxed_car_names(v):
    raw = re.sub(r"\s+", " ", v.car.strip())
    tokens = raw.split()

    trim_words = {
        "프리미엄","플러스","프리미엄플러스","인스퍼레이션","캘리그래피",
        "시그니처","노블레스","프레스티지","익스클루시브","스마트",
        "모던","럭셔리","스포츠","그래비티","블랙잉크","에어",
        "익스페디션","슈프림","엘리트","리미티드","플래티넘",
        "RE","LE","SE","SEL","H-픽","H픽"
    }

    power_words = {
        "하이브리드","HEV","EV","전기","디젤","LPG","엘피지",
        "가솔린","휘발유","PHEV","플러그인하이브리드"
    }

    names = [raw]

    stripped = [t for t in tokens if t not in trim_words]
    if stripped:
        s = " ".join(stripped)
        if s not in names:
            names.append(s)

    power = [t for t in stripped if t in power_words]
    base = [t for t in stripped if t not in power_words]

    if base:
        model = " ".join(base[:2])
        if power:
            s = (model + " " + " ".join(power)).strip()
            if s not in names:
                names.append(s)
        if model not in names:
            names.append(model)

    if tokens and tokens[0] not in names:
        names.append(tokens[0])

    return names[:4]

def build_relaxed_queries(v, car_name, stage=2):
    target = max(1, round(v.km / 10000))
    years = (v.year-1, v.year, v.year+1)

    qs = []
    if stage == 2:
        for y in years:
            qs += [
                f'{y} "{car_name}" {target}만km 중고차 판매',
                f'{y} "{car_name}" 중고차 매물 가격',
            ]
        qs += [
            f'site:encar.com "{car_name}" {v.year} 중고차',
            f'site:kbchachacha.com "{car_name}" {v.year} 중고차',
            f'site:kcar.com "{car_name}" {v.year} 중고차',
        ]
    else:
        for y in years:
            qs += [
                f'{car_name} {y} 중고차 {target}만km 판매가',
                f'{car_name} {y} 중고차 실매물',
                f'{car_name} {y} 중고차 가격 {target}만km',
            ]
        qs += [
            f'"{car_name}" 중고차 판매 매물',
            f'"{car_name}" 중고차 실매물 가격',
        ]

    seen, out = set(), []
    for q in qs:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out

def car_keywords(car):
    raw = re.findall(r"[가-힣A-Za-z0-9]+", (car or "").lower())
    stop = {"가솔린","휘발유","디젤","경유","하이브리드","hev","lpg","lpi","전기","ev",
            "2wd","4wd","awd","2륜","4륜","오토","자동","수동","터보",
            "프리미엄","프레스티지","노블레스","시그니처","캘리그래피",
            "인스퍼레이션","럭셔리","모던","스마트","스포츠","기본형","플러스","패키지","라인"}
    return [t for t in raw if t not in stop and not re.fullmatch(r"20\d{2}", t) and (len(t)>=2 or re.search(r"\d",t))][:8]

def powertrain_group(car):
    c=(car or "").lower().replace(" ","")
    if "하이브리드" in c or "hev" in c: return ["하이브리드","hev"]
    if "디젤" in c or "경유" in c: return ["디젤","경유"]
    if "lpg" in c or "lpi" in c or "엘피지" in c: return ["lpg","lpi","엘피지"]
    if "전기" in c or re.search(r"\bev\b", c): return ["전기","ev"]
    if "가솔린" in c or "휘발유" in c: return ["가솔린","휘발유"]
    return None

TRIM_RANK = {
    "스마트":1, "모던":2, "프레스티지":3, "프리미엄":3,
    "노블레스":4, "익스클루시브":4, "럭셔리":4,
    "시그니처":5, "인스퍼레이션":5, "스포츠":5,
    "캘리그래피":6, "그래비티":6, "플래티넘":6,
    "익스페디션":6, "블랙잉크":6
}

def detect_drive(text):
    t=(text or "").lower().replace(" ","")
    if any(x in t for x in ["4wd","awd","4륜","사륜"]):
        return "4WD"
    if any(x in t for x in ["2wd","2륜"]):
        return "2WD"
    return None

def detect_engine(text):
    t=(text or "").lower()
    m=re.search(r"(?<!\d)([1-6]\.\d)\s*(?:t|터보|l|리터)?", t)
    return m.group(1) if m else None

def detect_trim(text):
    t=(text or "")
    found=[]
    for name,rank in TRIM_RANK.items():
        if name.lower() in t.lower():
            found.append((rank,name))
    if not found:
        return None
    return sorted(found, reverse=True)[0][1]

def core_model_tokens(car):
    raw=re.findall(r"[가-힣A-Za-z0-9]+",(car or "").lower())
    stop={
        "가솔린","휘발유","디젤","경유","하이브리드","hev","lpg","lpi","엘피지",
        "전기","ev","phev","2wd","4wd","awd","2륜","4륜","오토","자동","수동",
        "터보","프리미엄","플러스","프레스티지","노블레스","시그니처",
        "캘리그래피","인스퍼레이션","럭셔리","모던","스마트","스포츠",
        "그래비티","플래티넘","익스페디션","블랙잉크","기본형","패키지","라인"
    }
    out=[]
    for t in raw:
        if t in stop or re.fullmatch(r"\d+(?:\.\d+)?",t) or re.fullmatch(r"20\d{2}",t):
            continue
        if len(t)>=2:
            out.append(t)
    return out[:3]

def trim_adjustment_pct(target_trim, source_trim):
    # 트림 서열은 차종마다 다를 수 있으므로 보정폭을 작게 제한한다.
    if not target_trim or not source_trim or target_trim==source_trim:
        return 0.0
    tr=TRIM_RANK.get(target_trim)
    sr=TRIM_RANK.get(source_trim)
    if tr is None or sr is None:
        return 0.0
    return max(-0.03,min(0.03,(tr-sr)*0.015))

def drive_adjustment_pct(target_drive, source_drive):
    # 목표가 4WD인데 비교매물이 2WD면 목표차 가격으로 +3%, 반대는 -3%.
    if not target_drive or not source_drive or target_drive==source_drive:
        return 0.0
    if target_drive=="4WD" and source_drive=="2WD":
        return 0.03
    if target_drive=="2WD" and source_drive=="4WD":
        return -0.03
    return 0.0

def _normalize_2digit_year(y2: int, target_year: int):
    # 중고차 검색에서 17년식, 21년형처럼 2자리 연식 표기가 흔함
    candidates=[1900+y2, 2000+y2]
    return min(candidates, key=lambda y: abs(y-target_year))

def nearest_year(text,pos,target_year):
    """
    차량 연식만 최대한 추출한다.
    게시일/시세기준일은 차량 연식으로 사용하지 않는다.
    """
    s=(text or "").lower()

    strong_patterns = [
        r"(20\d{2})\s*년\s*식",
        r"(20\d{2})\s*년\s*형",
        r"(20\d{2})\s*모델",
        r"최초\s*등록\s*[:：]?\s*(20\d{2})",
        r"등록\s*연도\s*[:：]?\s*(20\d{2})",
        r"연식\s*[:：]?\s*(20\d{2})",
        r"차량\s*연식\s*[:：]?\s*(20\d{2})",
        r"(?<!\d)(\d{2})\s*년\s*식",
        r"(?<!\d)(\d{2})\s*년\s*형",
    ]

    found=[]
    for pat in strong_patterns:
        for m in re.finditer(pat,s):
            raw=m.group(1)
            y=int(raw)
            if y<100:
                y=2000+y
            if 2000<=y<=2035:
                found.append((abs(m.start()-pos),y,0))

    for m in re.finditer(r"(?<!\d)(20\d{2})(?!\d)", s):
        y=int(m.group(1))
        around=s[max(0,m.start()-18):min(len(s),m.end()+22)]

        dateish = (
            re.search(rf"{y}\s*년\s*\d{{1,2}}\s*월", around) is not None
            or "기준" in around
            or "작성" in around
            or "게시" in around
            or "업데이트" in around
            or "시세표" in around
            or "기사" in around
        )
        vehicleish = any(k in around for k in [
            "연식","년식","년형","최초등록","등록연도","차량정보","매물정보","모델연도"
        ])
        if dateish and not vehicleish:
            continue

        found.append((abs(m.start()-pos),y,1))

    if not found:
        return None

    found.sort(key=lambda x:(x[2],x[0],abs(x[1]-target_year)))
    return found[0][1]

def mileage_values(text):
    vals=[]
    # 104,377km / 40,000 km
    for m in re.finditer(r"(?<!\d)(\d{1,3}(?:,\d{3})+)\s*(?:km|㎞|키로)", text, re.I):
        try:
            vals.append(int(m.group(1).replace(",","")))
        except (TypeError, ValueError):
            pass

    # 4만km / 10.6만 km
    for m in re.finditer(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*만\s*(?:km|㎞|키로)", text, re.I):
        try:
            vals.append(int(float(m.group(1))*10000))
        except (TypeError, ValueError):
            pass

    # 40000km 처럼 쉼표 없는 4~6자리 표기
    for m in re.finditer(r"(?<![\d,])(\d{4,6})\s*(?:km|㎞|키로)", text, re.I):
        try:
            val=int(m.group(1))
            if 1000 <= val <= 500000:
                vals.append(val)
        except (TypeError, ValueError):
            pass

    # 중복 제거
    return sorted(set(vals))

def nearest_mileage(text,target):
    vals=mileage_values(text)
    return min(vals,key=lambda x:abs(x-target)) if vals else None

def price_floor(year):
    if year>=2025: return 900
    if year>=2022: return 650
    if year>=2019: return 450
    if year>=2015: return 280
    return 150

def is_specific_listing_url(url: str, domain: str) -> bool:
    u=(url or "").lower()
    d=(domain or "").lower()

    # 플랫폼의 실제 차량 상세주소에서 자주 쓰는 패턴들
    detail_patterns={
        "encar.com":["cardetail", "carid=", "/cars/detail", "/detail/"],
        "kbchachacha.com":["carseq=", "/public/car/detail", "/car/detail", "detail.kbc"],
        "kcar.com":["carinfodtl", "scarcd=", "/car/detail", "/detail/"],
        "bobaedream.co.kr":["mycar_view", "no=", "/cyber/cview"],
        "autowini.com":["vehicle/", "/detail/"],
    }
    for host,pats in detail_patterns.items():
        if host in d and any(p in u for p in pats):
            return True
    return False

def source_type(text, domain, url="", year=None, km=None):
    guide_terms=["시세표","가격표","구매 가이드","구매가이드","가격 시세","연식별","중고 시세","시세 조회",
                 "가격 조회","총정리","비교","전망","평균","모델별","국내 매물 대수","중고차 플랫폼",
                 "검색결과","검색 결과","차량검색","매물검색","홈페이지"]
    listing_terms=["주행거리","km","차량번호","판매중","판매가","차량가","성능점검","최초등록","연식"]

    if any(g in text for g in guide_terms):
        return "reference"

    # URL 자체가 실제 차량 상세페이지면 가장 강한 근거
    if is_specific_listing_url(url,domain):
        return "listing"

    # 플랫폼 도메인이라는 이유만으로 개별매물 처리하지 않음.
    # 연식·주행거리 등 실제 차량 메타정보가 같이 있어야 개별매물로 인정.
    evidence=sum(1 for x in listing_terms if x in text)
    if year is not None: evidence+=2
    if km is not None: evidence+=2
    if evidence>=5 and (year is not None or km is not None):
        return "listing"

    if evidence>=2:
        return "reference"
    return "unknown"

def _extract_candidates_core(results,v):
    accepted=[]; rejected=[]
    patt=re.compile(r"(?<![\d,])(\d{1,3}(?:,\d{3})+|\d{3,5})\s*만\s*원")
    kws=car_keywords(v.car)
    core=core_model_tokens(v.car)
    pt=powertrain_group(v.car)
    floor=price_floor(v.year)

    target_drive=detect_drive(v.car)
    target_engine=detect_engine(v.car)
    target_trim=detect_trim(v.car)

    bad=["월납","월 납","월렌트","월 렌트","월리스","월 리스","보증금","선수금","지원금","취등록","보험료",
         "수리비","부품비","사고비","계약금","할인","혜택","캐시백","리스료","렌트료"]

    for idx,x in enumerate(results):
        title=clean_text(x.get("title",""))
        desc=clean_text(x.get("description",""))
        domain=x.get("domain","")
        url=x.get("url","")
        text=f"{title} {desc}".lower()

        km=nearest_mileage(text,v.km)
        kw_hits=sum(1 for k in kws if k in text)
        core_hits=sum(1 for k in core if k in text)
        pt_match=True if not pt else any(term in text for term in pt)

        source_drive=detect_drive(text)
        source_engine=detect_engine(text)
        source_trim=detect_trim(text)

        # 8.4차: 모델명 자체가 확인되면 세부 트림/구동방식 차이로 탈락시키지 않는다.
        model_ok=(core_hits>=1) if core else (kw_hits>=1 if kws else True)
        per_url=[]

        for m in patt.finditer(text):
            price=int(m.group(1).replace(",",""))
            start,end=m.span()
            context=text[max(0,start-140):min(len(text),end+140)]
            yr=nearest_year(text,start,v.year)
            stype=source_type(text,domain,url,yr,km)
            reason=None

            if price<floor:
                reason=f"가격 하한({floor}만원) 미만"
            elif price>30000:
                reason="비현실적 고가"
            elif any(term in context for term in bad):
                reason="월납/보증금/할인·비용성 금액"
            elif not model_ok:
                reason="차종 유사도 부족"
            elif pt and not pt_match:
                reason="동력원 불일치"
            elif yr and abs(yr-v.year)>1:
                reason=f"연식 범위 초과({yr})"
            elif km and abs(km-v.km)>40000:
                reason=f"주행거리 범위 초과({km:,}km)"
            elif stype=="unknown":
                reason="개별매물 근거 부족"

            score=min(core_hits,3)*4 + min(kw_hits,4)
            score += 7 if stype=="listing" else (-4 if stype=="reference" else -2)
            score += 8 if yr==v.year else (5 if yr and abs(yr-v.year)==1 else (-3 if yr is None else -6))
            if pt and pt_match:
                score+=4

            if km:
                diff=abs(km-v.km)
                score += 7 if diff<=10000 else (5 if diff<=20000 else (2 if diff<=40000 else -6))
            else:
                score -= 3

            if yr is not None and km is not None:
                score += 5
            if is_specific_listing_url(url,domain):
                score += 6

            # 8.4.1차: 실제 상세매물 + 핵심 모델/동력원 일치 시 강하게 가산
            if stype=="listing" and model_ok and pt_match:
                score += 5
            if any(term in context for term in ["판매가","차량가","판매중"]):
                score+=2

            # 구동/배기량/트림은 탈락 조건이 아니라 유사도와 가격보정 요소.
            if target_drive and source_drive:
                score += 2 if target_drive==source_drive else 0
            if target_engine and source_engine:
                score += 2 if target_engine==source_engine else -1
            if target_trim and source_trim:
                score += 2 if target_trim==source_trim else 0

            drive_adj=drive_adjustment_pct(target_drive,source_drive)
            trim_adj=trim_adjustment_pct(target_trim,source_trim)

            rec={
                "price":price,"year":yr,"score":score,"mileage":km,"title":title,"url":url,
                "domain":domain,"reason":reason or "채택","source_type":stype,
                "target_year":v.year,"target_km":v.km,
                "target_drive":target_drive,"source_drive":source_drive,
                "target_engine":target_engine,"source_engine":source_engine,
                "target_trim":target_trim,"source_trim":source_trim,
                "drive_adjust_pct":drive_adj,"trim_adjust_pct":trim_adj,
                "core_model_match":model_ok,
                "powertrain_match":pt_match
            }

            if reason is None:
                per_url.append(rec)
            else:
                rejected.append(rec)

        if per_url:
            best=sorted(
                per_url,
                key=lambda c:(-c["score"],
                              99 if c["year"] is None else abs(c["year"]-v.year),
                              999999 if c["mileage"] is None else abs(c["mileage"]-v.km))
            )[0]

            # 실제 개별매물은 기준을 약간 완화하되 참고자료는 계속 엄격하게 유지.
            min_score=10 if best["source_type"]=="listing" else 17
            if best["score"]>=min_score:
                accepted.append(best)
                for extra in per_url[1:]:
                    extra=dict(extra)
                    extra["reason"]="동일 URL의 보조 가격"
                    rejected.append(extra)
            else:
                best=dict(best)
                best["reason"]="유사도 점수 부족"
                rejected.append(best)

    return accepted,rejected

def extract_candidates(results,v):
    accepted=[]
    rejected=[]
    for item in (results or []):
        try:
            a,r=_extract_candidates_core([item],v)
            accepted.extend(a)
            rejected.extend(r)
        except Exception as e:
            title=""
            url=""
            if isinstance(item,dict):
                title=clean_text(item.get("title",""))
                url=clean_text(item.get("url",""))
            rejected.append({
                "price":0,
                "year":None,
                "score":0,
                "mileage":None,
                "title":title or "검색결과 처리 오류",
                "url":url,
                "domain":domain_of(url),
                "reason":f"검색결과 처리 오류({type(e).__name__})",
                "source_type":"unknown",
                "target_year":v.year,
                "target_km":v.km
            })
    return accepted,rejected

def normalize_year(price,source_year,target_year):
    if not source_year or source_year==target_year:
        return float(price)
    diff=source_year-target_year
    return price*(0.95**diff) if diff>0 else price*(1.05**(-diff))

def adjust_km(price,source_km,target_km):
    if not source_km:
        return price
    diff=target_km-source_km
    rate=max(-0.06,min(0.06,-(diff/10000)*0.01))
    return price*(1+rate)

def weighted_median(values):
    arr=sorted(values,key=lambda x:x[0])
    total=sum(w for _,w in arr)
    acc=0
    for value,weight in arr:
        acc+=weight
        if acc>=total/2:
            return value
    return arr[-1][0]

def robust_market(cands):
    if not cands:
        return None

    listing=[c for c in cands if c["source_type"]=="listing"]
    reference=[c for c in cands if c["source_type"]!="listing"]

    # 8.1차 핵심: 참고자료는 대표 소매시세 계산에 절대 넣지 않는다.
    # 실제 개별매물이 하나도 없을 때만 계산 불가 처리한다.
    if not listing:
        return None

    enriched=[]
    for c in listing:
        adj=normalize_year(c["price"],c.get("year"),c["target_year"])
        adj=adjust_km(adj,c.get("mileage"),c["target_km"])
        drive_adj=float(c.get("drive_adjust_pct") or 0)
        trim_adj=float(c.get("trim_adjust_pct") or 0)
        adj=adj*(1+drive_adj)*(1+trim_adj)
        cc=dict(c)
        cc["adjusted_price"]=round(adj)
        notes=[]
        if drive_adj:
            notes.append(f"구동 {drive_adj*100:+.0f}%")
        if trim_adj:
            notes.append(f"트림 {trim_adj*100:+.1f}%")
        cc["adjustment_note"]=" / ".join(notes) if notes else "연식·주행거리 보정"
        enriched.append(cc)

    vals=[c["adjusted_price"] for c in enriched]
    med=statistics.median(vals)
    mad=statistics.median([abs(x-med) for x in vals]) if vals else 0

    filtered=[]
    out=[]
    for c in enriched:
        p=c["adjusted_price"]
        ratio_ok=med*0.78<=p<=med*1.22
        mad_ok=(mad==0 or abs(p-med)<=max(2.8*mad,med*0.14))
        if ratio_ok and mad_ok:
            filtered.append(c)
        else:
            cc=dict(c)
            cc["reason"]="개별매물 가격 편차/통계적 이상값"
            out.append(cc)

    # 이상값 제거 결과가 전부 사라지면 원자료를 다시 쓰되 신뢰도를 낮춘다.
    if not filtered:
        filtered=enriched
        out=[]

    wm=weighted_median([
        (c["adjusted_price"],max(1,c["score"]))
        for c in filtered
    ])
    prices=sorted(c["adjusted_price"] for c in filtered)

    if len(prices)>=4:
        q=statistics.quantiles(prices,n=4,method="inclusive")
        low,high=round(q[0]),round(q[2])
    else:
        low,high=min(prices),max(prices)

    lc=len(filtered)
    exact_listing_meta=sum(
        1 for c in filtered
        if c.get("year") is not None and c.get("mileage") is not None
    )

    # 가격 편차: 보정가격의 최대-최소가 중앙값 대비 얼마나 벌어지는지 계산
    spread_ratio=((max(prices)-min(prices))/wm) if len(prices)>=2 and wm else 0
    if spread_ratio>=0.25:
        dispersion="큼"
    elif spread_ratio>=0.15:
        dispersion="보통"
    else:
        dispersion="작음"

    # 실제 개별매물 + 연식/주행거리 확인 건수 + 가격 편차를 함께 반영
    reasons=[]
    if lc < 3:
        reasons.append("실제 개별매물 3건 미만")
    if exact_listing_meta < 3:
        reasons.append("연식+주행거리 확인 개별매물 3건 미만")
    if dispersion=="큼":
        reasons.append("비교매물 간 가격 편차 큼")

    if lc>=5 and exact_listing_meta>=5 and dispersion=="작음":
        conf="높음"; err=4
    elif lc>=3 and exact_listing_meta>=3 and dispersion!="큼":
        conf="보통"; err=7
    elif lc>=2 and exact_listing_meta>=2:
        conf="낮음"; err=10
    else:
        conf="매우 낮음"; err=15

    # 가격 편차가 크면 한 단계 더 보수적으로
    if dispersion=="큼":
        if conf=="높음":
            conf="보통"; err=max(err,7)
        elif conf=="보통":
            conf="낮음"; err=max(err,10)
        elif conf=="낮음":
            conf="매우 낮음"; err=max(err,15)

    provisional = (lc < 3 or exact_listing_meta < 3 or dispersion=="큼")

    # 참고자료는 계산에서 제외하지만 화면 검증용으로 별도 보관
    ref_preview=[]
    for c in reference[:10]:
        cc=dict(c)
        adj=normalize_year(c["price"],c.get("year"),c["target_year"])
        adj=adjust_km(adj,c.get("mileage"),c["target_km"])
        drive_adj=float(c.get("drive_adjust_pct") or 0)
        trim_adj=float(c.get("trim_adjust_pct") or 0)
        adj=adj*(1+drive_adj)*(1+trim_adj)
        cc["adjusted_price"]=round(adj)
        notes=[]
        if drive_adj:
            notes.append(f"구동 {drive_adj*100:+.0f}%")
        if trim_adj:
            notes.append(f"트림 {trim_adj*100:+.1f}%")
        cc["adjustment_note"]=" / ".join(notes) if notes else "연식·주행거리 보정"
        ref_preview.append(cc)

    return {
        "count":len(filtered),
        "listing_count":lc,
        "reference_count":len(reference),
        "exact_meta_count":exact_listing_meta,
        "confidence":conf,
        "error_pct":err,
        "provisional":provisional,
        "dispersion":dispersion,
        "spread_pct":round(spread_ratio*100,1),
        "confidence_reasons":reasons,
        "median":int(round(wm)),
        "low":int(low),
        "high":int(high),
        "prices":prices[:30],
        "adopted":sorted(
            filtered,
            key=lambda c:(-c["score"],abs(c["adjusted_price"]-wm))
        )[:20],
        "references":ref_preview,
        "outliers":out[:20]
    }

def base_discount(v):
    age=max(0,2026-v.year)
    if age<=1 and v.km<=30000:
        return 13.5
    if age<=3 and v.km<=60000:
        return 15.5
    return 17.5

def calc_auction(v,market_mid):
    d=base_discount(v)

    if v.km>180000: d+=6
    elif v.km>150000: d+=5
    elif v.km>120000: d+=4
    elif v.km>100000: d+=3
    elif v.km>80000: d+=1.5
    elif v.km<30000: d-=0.5

    d+=min(v.accident_count*0.8,4)

    aa=v.accident_amount
    if aa>=1500: d+=6
    elif aa>=1000: d+=5
    elif aa>=700: d+=4
    elif aa>=500: d+=2.5
    elif aa>=300: d+=1.5
    elif aa>=150: d+=0.7

    p=v.parts_amount
    if p>=900: d+=4
    elif p>=700: d+=3
    elif p>=500: d+=2.5
    elif p>=300: d+=1.5
    elif p>=150: d+=0.7

    d+=v.uninsured+v.use_history*1.7+v.frame*3.5+v.condition*1.3+v.liquidity*1.5+v.special*1.5
    d=max(10,min(35,d))

    auction=market_mid*(1-d/100)
    spread=max(50,auction*0.045)

    low=round((auction-spread)/10)*10
    high=round((auction+spread)/10)*10
    target=round(auction/10)*10
    upper=round((auction+spread*1.25)/10)*10

    verdict="보수적 접근" if d>=25 else ("조건부 검토" if d>=20 else "매입 검토 가능")

    return {
        "discount_rate":round(d,1),
        "auction_low":int(low),
        "auction_high":int(high),
        "target":int(target),
        "upper":int(upper),
        "verdict":verdict
    }

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "provider": SEARCH_PROVIDER})

@app.post("/api/analyze")
def analyze(v: Vehicle):
    try:
        web=[]
        errors=[]
        queries=[]
        search_stage=1

        def run_queries(qs, max_calls):
            nonlocal web, queries
            existing=set(queries)
            count=0
            for q in qs:
                if q in existing:
                    continue
                if count >= max_calls:
                    break
                try:
                    web.extend(search_web(q))
                except Exception as e:
                    errors.append(str(e))
                queries.append(q)
                count += 1

        def recalc():
            nonlocal web
            web=dedupe_results(web)
            return extract_candidates(web,v)

        def verified_listing_count(items):
            return sum(
                1 for c in items
                if c.get("source_type")=="listing"
                and c.get("year") is not None
                and c.get("mileage") is not None
            )

        run_queries(build_queries(v), 5)
        accepted,rejected=recalc()

        relaxed_names=relaxed_car_names(v)

        if verified_listing_count(accepted) < 3 and len(relaxed_names) >= 2:
            search_stage=2
            for name in relaxed_names[1:3]:
                run_queries(build_relaxed_queries(v,name,stage=2), 4)
                accepted,rejected=recalc()
                if verified_listing_count(accepted) >= 3:
                    break

        if verified_listing_count(accepted) < 3:
            search_stage=3
            fallback_name = relaxed_names[1] if len(relaxed_names) >= 2 else relaxed_names[0]
            run_queries(build_relaxed_queries(v,fallback_name,stage=3), 6)
            accepted,rejected=recalc()

        if v.manual_prices:
            for x in v.manual_prices:
                if x and x>0:
                    accepted.append({
                        "price":float(x),"year":v.year,"score":30,"mileage":v.km,
                        "title":"수동 입력 유사매물","url":"","domain":"",
                        "reason":"사용자 확인 매물","source_type":"listing",
                        "target_year":v.year,"target_km":v.km
                    })

        market=robust_market(accepted)

        if not market:
            return JSONResponse({
                "ok":False,
                "message":"단계적 검색까지 진행했지만 조건에 맞는 실제 비교매물을 충분히 찾지 못했어. 필터는 유지한 채 검색 범위만 넓혔고, 억지로 유사도가 낮은 차량을 넣지는 않았어. 실제 유사매물 가격을 수동으로 추가하면 계산할 수 있어.",
                "queries":queries,
                "search_stage":search_stage,
                "relaxed_names":relaxed_names,
                "search_results":web[:50],
                "rejected":rejected[:60],
                "search_errors":errors
            })

        insufficient = (
            market["listing_count"] < 3
            or market["exact_meta_count"] < 3
        )
        market["market_status"] = "시세 확정 불가" if insufficient else (
            "잠정 시세" if market["provisional"] else "시세 확정"
        )

        auction=calc_auction(v,market["median"])
        if insufficient:
            auction["verdict"] = "비교매물 부족 · 공매가 확정 불가"

        return {
            "ok":True,
            "queries":queries,
            "search_stage":search_stage,
            "relaxed_names":relaxed_names,
            "market":market,
            "auction":auction,
            "search_results":web[:50],
            "rejected":rejected[:60],
            "search_errors":errors
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={
            "ok": False,
            "message": f"분석 중 오류: {type(e).__name__}: {str(e)}",
            "error_type": type(e).__name__,
        })
