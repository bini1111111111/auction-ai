from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from html import unescape
from urllib.parse import urlparse
import os, re, statistics, requests

app = FastAPI(title="공매가 AI 8.2차")
templates = Jinja2Templates(directory="templates")

SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "none").lower()
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

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

def clean_text(s: str) -> str:
    s = unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def domain_of(url: str) -> str:
    try:
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
            timeout=15,
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
            timeout=15,
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
    for x in results:
        url = (x.get("url") or "").split("#")[0].rstrip("/")
        key = url or x.get("title", "")
        if not key or key in seen:
            continue
        seen.add(key)
        y = dict(x)
        y["url"] = url
        y["domain"] = domain_of(url)
        out.append(y)
    return out

def build_queries(v):
    km_man = max(1, round(v.km / 10000))
    c = v.car.strip()
    return [
        f'"{c}" {v.year} {km_man}만km 중고차 매물',
        f'{v.year}년식 {c} {km_man}만km 판매가',
        f'site:encar.com {v.year} "{c}" {km_man}만km',
        f'site:kbchachacha.com {v.year} "{c}" {km_man}만km',
        f'site:kcar.com {v.year} "{c}" {km_man}만km',
    ]

def build_expanded_queries(v):
    """1차 결과에서 검증 개별매물이 3건 미만일 때만 추가 검색."""
    c = v.car.strip()
    target = max(1, round(v.km / 10000))
    bands = sorted(set([
        max(1, target-4), max(1, target-2), target,
        target+2, target+4
    ]))
    qs = []

    # 목표 연식 ±1년 × 주행거리 구간
    for y in (v.year-1, v.year, v.year+1):
        for km_man in bands:
            qs.append(f'{y} "{c}" {km_man}만km 중고차 매물 가격')

    # 주요 플랫폼별 상세 매물 탐색
    for domain in ("encar.com", "kbchachacha.com", "kcar.com"):
        for y in (v.year-1, v.year, v.year+1):
            qs.append(f'site:{domain} {y} "{c}" 중고차 {target}만km')

    # 표현 차이 대응
    qs += [
        f'"{c}" "{v.year}년식" 중고차 판매 {target}만',
        f'"{c}" "{v.year}년형" 중고차 {target}만km 가격',
        f'"{c}" "최초등록 {v.year}" {target}만km',
        f'{c} {v.year} 중고차 실매물 {target}만km',
    ]

    # 중복 제거
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

def _normalize_2digit_year(y2: int, target_year: int):
    # 중고차 검색에서 17년식, 21년형처럼 2자리 연식 표기가 흔함
    candidates=[1900+y2, 2000+y2]
    return min(candidates, key=lambda y: abs(y-target_year))

def nearest_year(text, pos, target_year):
    matches=[]

    # 2021년식 / 2021년형 / 2021년 / 최초등록 2021
    patterns=[
        r"(?<!\d)(20\d{2})\s*(?:년식|년형|년|MY)?",
        r"(?:최초등록|등록연월|등록일|연식)\s*[:：]?\s*(20\d{2})",
        r"(?<!\d)(\d{2})\s*(?:년식|년형)",
        r"(?:최초등록|등록연월|연식)\s*[:：]?\s*(\d{2})\s*년",
    ]

    for pi,pat in enumerate(patterns):
        for m in re.finditer(pat,text,re.I):
            raw=int(m.group(1))
            y=raw if raw>=1900 else _normalize_2digit_year(raw,target_year)
            d=min(abs(m.start()-pos),abs(m.end()-pos))
            # 가격과 다소 떨어져 있어도 같은 검색 snippet 안의 연식이면 인정
            if d<=180:
                bonus=0 if pi<2 else 8
                matches.append((d+bonus,abs(y-target_year),y))

    return min(matches)[2] if matches else None

def mileage_values(text):
    vals=[]
    for m in re.finditer(r"(?<!\d)(\d{1,3}(?:,\d{3})+)\s*(?:km|㎞|키로)", text, re.I):
        try: vals.append(int(m.group(1).replace(",","")))
        except: pass
    for m in re.finditer(r"(?<!\d)(\d{1,2}(?:\.\d+)?)\s*만\s*(?:km|㎞|키로)", text, re.I):
        try: vals.append(int(float(m.group(1))*10000))
        except: pass
    return vals

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

def extract_candidates(results,v):
    accepted=[]; rejected=[]
    patt=re.compile(r"(?<![\d,])(\d{1,3}(?:,\d{3})+|\d{3,5})\s*만\s*원")
    kws=car_keywords(v.car)
    pt=powertrain_group(v.car)
    floor=price_floor(v.year)
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
        pt_match=True if not pt else any(term in text for term in pt)
        model_ok=kw_hits>=1 if kws else True
        per_url=[]

        for m in patt.finditer(text):
            price=int(m.group(1).replace(",",""))
            start,end=m.span()
            context=text[max(0,start-120):min(len(text),end+120)]
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

            score=min(kw_hits,4)*2
            score += 7 if stype=="listing" else (-4 if stype=="reference" else -2)
            score += 8 if yr==v.year else (5 if yr and abs(yr-v.year)==1 else (-3 if yr is None else -6))
            if pt and pt_match: score+=3

            if km:
                diff=abs(km-v.km)
                score += 7 if diff<=10000 else (5 if diff<=20000 else (2 if diff<=40000 else -6))
            else:
                score -= 3

            # 연식과 주행거리가 모두 확인된 실제 매물은 확실하게 우선
            if yr is not None and km is not None:
                score += 5
            if is_specific_listing_url(url,domain):
                score += 4
            if any(term in context for term in ["판매가","차량가","판매중"]):
                score+=2

            rec={"price":price,"year":yr,"score":score,"mileage":km,"title":title,"url":url,
                 "domain":domain,"reason":reason or "채택","source_type":stype,
                 "target_year":v.year,"target_km":v.km}

            if reason is None:
                per_url.append(rec)
            else:
                rejected.append(rec)

        if per_url:
            best=sorted(per_url,key=lambda c:(-c["score"],99 if c["year"] is None else abs(c["year"]-v.year),
                                              999999 if c["mileage"] is None else abs(c["mileage"]-v.km)))[0]
            min_score=15 if best["source_type"]=="listing" else 17
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
        cc=dict(c)
        cc["adjusted_price"]=round(adj)
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
        cc["adjusted_price"]=round(adj)
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
    web=[]
    errors=[]
    queries=build_queries(v)
    expanded_used=False

    # 1차 검색
    for q in queries:
        try:
            web.extend(search_web(q))
        except Exception as e:
            errors.append(str(e))

    web=dedupe_results(web)
    accepted,rejected=extract_candidates(web,v)

    def verified_listing_count(items):
        return sum(
            1 for c in items
            if c.get("source_type")=="listing"
            and c.get("year") is not None
            and c.get("mileage") is not None
        )

    # 8.2차: 실제 검증 개별매물이 3건 미만일 때만 확장 검색
    if verified_listing_count(accepted) < 3:
        expanded_used=True
        extra_queries=build_expanded_queries(v)
        existing=set(queries)
        extra_queries=[q for q in extra_queries if q not in existing]

        # API 과소비를 막으면서도 검색 폭은 충분히 확대
        for q in extra_queries[:18]:
            try:
                web.extend(search_web(q))
            except Exception as e:
                errors.append(str(e))
        queries += extra_queries[:18]

        web=dedupe_results(web)
        accepted,rejected=extract_candidates(web,v)

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
            "message":"조건에 맞는 실제 비교매물을 찾지 못했어. 차량명/트림을 더 정확히 입력하거나 실제 유사매물 가격을 수동으로 입력해줘.",
            "queries":queries,
            "expanded_search":expanded_used,
            "search_results":web[:40],
            "rejected":rejected[:50],
            "search_errors":errors
        })

    # 8.2차 안전장치:
    # 실제 개별매물 3건 + 연식/주행거리 확인 3건이 아니면
    # 공매가 숫자를 '확정'으로 취급하지 않는다.
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
        "expanded_search":expanded_used,
        "market":market,
        "auction":auction,
        "search_results":web[:40],
        "rejected":rejected[:50],
        "search_errors":errors
    }

