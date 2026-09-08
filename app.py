
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, List
import os, re, statistics, requests
from urllib.parse import quote

app = FastAPI(title="공매가 AI 4차")
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

def search_web(query: str):
    results = []
    if SEARCH_PROVIDER == "brave" and BRAVE_API_KEY:
        r = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"Accept":"application/json","X-Subscription-Token":BRAVE_API_KEY},
            params={"q":query,"count":20,"country":"kr","search_lang":"ko"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        for x in data.get("web", {}).get("results", []):
            results.append({"title": x.get("title",""), "url": x.get("url",""), "description": x.get("description","")})

    elif SEARCH_PROVIDER == "serpapi" and SERPAPI_KEY:
        r = requests.get(
            "https://serpapi.com/search.json",
            params={"engine":"google","q":query,"hl":"ko","gl":"kr","api_key":SERPAPI_KEY,"num":20},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        for x in data.get("organic_results", []):
            results.append({"title":x.get("title",""),"url":x.get("link",""),"description":x.get("snippet","")})
    return results

def extract_prices(results):
    # 검색 결과 제목/설명에 나타난 '3,250만원', '3250 만원' 형태를 보수적으로 추출
    prices = []
    pattern = re.compile(r'(?<!\d)(\d{3,5}(?:,\d{3})?)\s*만\s*원?')
    for x in results:
        txt = f"{x.get('title','')} {x.get('description','')}"
        for m in pattern.findall(txt):
            v = int(m.replace(",",""))
            if 300 <= v <= 30000:
                prices.append(v)
    return prices

def robust_market(prices):
    if not prices:
        return None
    prices = sorted(prices)
    if len(prices) >= 5:
        q1 = statistics.quantiles(prices, n=4, method='inclusive')[0]
        q3 = statistics.quantiles(prices, n=4, method='inclusive')[2]
        iqr = q3-q1
        filtered = [p for p in prices if q1-1.5*iqr <= p <= q3+1.5*iqr]
    else:
        filtered = prices
    if not filtered:
        filtered = prices
    return {
        "count": len(filtered),
        "low": int(min(filtered)),
        "high": int(max(filtered)),
        "median": int(statistics.median(filtered)),
        "prices": filtered[:30],
    }

def calc_auction(v: Vehicle, market_mid: float):
    d = 10.5
    km = v.km
    if km > 180000: d += 6
    elif km > 150000: d += 5
    elif km > 120000: d += 3
    elif km > 100000: d += 2
    elif km < 30000: d -= 1

    d += min(v.accident_count * 0.8, 4)
    aa = v.accident_amount
    if aa >= 1200: d += 5
    elif aa >= 900: d += 4
    elif aa >= 700: d += 3
    elif aa >= 500: d += 2
    elif aa >= 300: d += 1

    p = v.parts_amount
    if p >= 700: d += 3.5
    elif p >= 500: d += 2.5
    elif p >= 300: d += 1.5
    elif p >= 150: d += 0.7

    d += v.uninsured
    d += v.use_history * 1.5
    d += v.frame * 3
    d += v.condition * 1.2
    d += v.liquidity * 1.5
    d += v.special * 1.5
    d = max(7, min(30, d))

    auction = market_mid * (1 - d/100)
    spread = max(50, auction*0.045)
    low = round((auction-spread)/10)*10
    high = round((auction+spread)/10)*10
    target = round(auction/10)*10
    upper = round((auction+spread*1.35)/10)*10

    if target/market_mid >= .88:
        verdict = "매입 검토 가능"
    elif target/market_mid >= .82:
        verdict = "조건부 검토"
    else:
        verdict = "보수적 접근"

    return {
        "discount_rate": round(d,1),
        "auction_low": int(low),
        "auction_high": int(high),
        "target": int(target),
        "upper": int(upper),
        "verdict": verdict
    }

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "provider": SEARCH_PROVIDER
    })

@app.post("/api/analyze")
def analyze(v: Vehicle):
    query = f'{v.year} {v.car} {v.km}km 중고차 가격'
    web_results = []
    prices = []

    try:
        web_results = search_web(query)
        prices = extract_prices(web_results)
    except Exception as e:
        web_results = [{"title":"검색 오류", "description":str(e), "url":""}]

    if v.manual_prices:
        prices.extend([float(x) for x in v.manual_prices if x and x > 0])

    market = robust_market(prices)
    if not market:
        return JSONResponse({
            "ok": False,
            "message": "자동 검색에서 가격을 충분히 찾지 못했어. 유사매물 가격을 수동으로 3개 이상 입력해줘.",
            "query": query,
            "search_results": web_results[:10]
        })

    auction = calc_auction(v, market["median"])
    return {
        "ok": True,
        "query": query,
        "market": market,
        "auction": auction,
        "search_results": web_results[:10]
    }
