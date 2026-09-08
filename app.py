from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from html import unescape
import os, re, statistics, requests

app = FastAPI(title="공매가 AI 5차")
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


def search_web(query: str) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []

    if SEARCH_PROVIDER == "brave" and BRAVE_API_KEY:
        r = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": BRAVE_API_KEY
            },
            params={
                "q": query,
                "count": 20,
                "country": "kr",
                "search_lang": "ko"
            },
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

        for x in data.get("web", {}).get("results", []):
            results.append({
                "title": clean_text(x.get("title", "")),
                "url": x.get("url", ""),
                "description": clean_text(x.get("description", "")),
            })

    elif SEARCH_PROVIDER == "serpapi" and SERPAPI_KEY:
        r = requests.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google",
                "q": query,
                "hl": "ko",
                "gl": "kr",
                "api_key": SERPAPI_KEY,
                "num": 20
            },
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

        for x in data.get("organic_results", []):
            results.append({
                "title": clean_text(x.get("title", "")),
                "url": x.get("link", ""),
                "description": clean_text(x.get("snippet", "")),
            })

    return results


def dedupe_results(results: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    out = []

    for x in results:
        key = (x.get("url", ""), x.get("title", ""))

        if key in seen:
            continue

        seen.add(key)
        out.append(x)

    return out


def build_queries(v: Vehicle) -> List[str]:
    km_man = max(1, round(v.km / 10000))

    return [
        f'{v.year}년식 {v.car} {km_man}만km 중고차 판매 가격 만원',
        f'{v.year} {v.car} 중고차 시세 가격',
    ]


def car_keywords(car: str) -> List[str]:
    raw = re.findall(r"[가-힣A-Za-z0-9]+", (car or "").lower())

    stop = {
        "가솔린", "휘발유", "디젤", "경유", "하이브리드", "hev",
        "lpg", "lpi", "전기", "ev",
        "2wd", "4wd", "awd", "2륜", "4륜",
        "오토", "자동", "수동", "가솔린터보", "터보",
        "프리미엄", "프레스티지", "노블레스", "시그니처",
        "캘리그래피", "인스퍼레이션", "럭셔리",
        "모던", "스마트", "스포츠", "기본형",
        "플러스", "패키지", "라인",
    }

    out = []

    for t in raw:
        if t in stop or re.fullmatch(r"20\d{2}", t):
            continue

        if len(t) >= 2 or re.search(r"\d", t):
            out.append(t)

    return out[:6]


def powertrain_group(car: str) -> Optional[List[str]]:
    c = (car or "").lower().replace(" ", "")

    if "하이브리드" in c or "hev" in c:
        return ["하이브리드", "hev"]

    if "디젤" in c or "경유" in c:
        return ["디젤", "경유"]

    if "lpg" in c or "lpi" in c or "엘피지" in c:
        return ["lpg", "lpi", "엘피지"]

    if "전기" in c or re.search(r"\bev\b", c):
        return ["전기", "ev"]

    if "가솔린" in c or "휘발유" in c:
        return ["가솔린", "휘발유"]

    return None


def nearest_year(text: str, pos: int) -> Optional[int]:
    matches = []

    for m in re.finditer(r"(?<!\d)(20\d{2})(?:\s*년식|\s*년)?", text):
        y = int(m.group(1))
        distance = min(abs(m.start() - pos), abs(m.end() - pos))

        if distance <= 80:
            matches.append((distance, y))

    return min(matches)[1] if matches else None


def mileage_from_text(text: str) -> Optional[int]:
    vals = []

    for m in re.finditer(
        r"(?<!\d)(\d{1,3}(?:,\d{3})+)\s*(?:km|㎞|키로)",
        text,
        re.I
    ):
        try:
            vals.append(int(m.group(1).replace(",", "")))
        except ValueError:
            pass

    for m in re.finditer(
        r"(?<!\d)(\d{1,2}(?:\.\d+)?)\s*만\s*(?:km|㎞|키로)",
        text,
        re.I
    ):
        try:
            vals.append(int(float(m.group(1)) * 10000))
        except ValueError:
            pass

    return vals[0] if vals else None


def price_floor(year: int) -> int:근
    if year >= 2024:
        return 700

    if year >= 2020:
        return 500

    if year >= 2015:
        return 300

    return 150


def extract_price_candidates(
    results: List[Dict[str, str]],
    v: Vehicle
):
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    price_pattern = re.compile(
        r"(?<![\d,])(\d{1,3}(?:,\d{3})+|\d{3,5})\s*만\s*원"
    )

    keywords = car_keywords(v.car)
    pt = powertrain_group(v.car)
    floor = price_floor(v.year)

    bad_terms = [
        "월납", "월 납",
        "월렌트", "월 렌트",
        "월리스", "월 리스",
        "보증금", "선수금",
        "지원금", "취등록",
        "보험료", "수리비",
        "부품비", "사고비",
        "계약금", "할인",
        "혜택", "캐시백",
    ]

    good_terms = [
        "판매", "판매가",
        "가격", "시세",
        "매물", "중고",
        "차량가", "년식",
        "만원"
    ]

    for idx, x in enumerate(results):
        title = clean_text(x.get("title", ""))
        desc = clean_text(x.get("description", ""))

        text = f"{title} {desc}".lower()

        result_mileage = mileage_from_text(text)

        kw_hits = sum(
            1 for k in keywords
            if k.lower() in text
        )

        has_target_year = str(v.year) in text

        pt_match = True

        if pt:
            pt_match = any(term in text for term in pt)

        conflict = False

        if pt:
            other_groups = [
                ["하이브리드", "hev"],
                ["디젤", "경유"],
                ["lpg", "lpi", "엘피지"],
                ["가솔린", "휘발유"]
            ]

            for g in other_groups:
                if g == pt:
                    continue

                if any(term in text for term in g) and not pt_match:
                    conflict = True
                    break

        for m in price_pattern.finditer(text):
            raw = m.group(1)

            try:
                price = int(raw.replace(",", ""))
            except ValueError:
                continue

            start, end = m.span()

            context = text[
                max(0, start - 75):
                min(len(text), end + 75)
            ]

            assoc_year = nearest_year(text, start)

            reason = None

            if price < floor:
                reason = f"가격 하한({floor}만원) 미만"

            elif price > 30000:
                reason = "비현실적 고가"

            elif any(term in context for term in bad_terms):
                reason = "월납/보증금/할인·비용성 금액"

            elif assoc_year and abs(assoc_year - v.year) >= 2:
                reason = f"연식 불일치({assoc_year})"

            elif conflict:
                reason = "동력원 불일치"

            elif not any(term in context for term in good_terms):
                reason = "차량 판매가격 문맥 부족"

            score = 1

            score += min(kw_hits, 3)

            if has_target_year:
                score += 1

            if pt_match and pt:
                score += 3

            if assoc_year == v.year:
                score += 5

            elif assoc_year and abs(assoc_year - v.year) == 1:
                score += 2

            elif assoc_year is None:
                score += 1

            if any(
                term in context
                for term in [
                    "판매가",
                    "차량가",
                    "중고차 가격",
                    "시세"
                ]
            ):
                score += 1

            if result_mileage:
                diff = abs(result_mileage - v.km)

                if diff <= 20000:
                    score += 2

                elif diff <= 40000:
                    score += 1

                elif diff >= 80000:
                    score -= 1

            rec = {
                "price": price,
                "year": assoc_year,
                "score": score,
                "mileage": result_mileage,
                "title": title,
                "url": x.get("url", ""),
                "context": context[:180],
                "reason": reason or "채택",
                "source_index": idx,
            }

            if reason is None and score >= 4:
                accepted.append(rec)

            else:
                if reason is None:
                    rec["reason"] = "유사도 점수 부족"

                rejected.append(rec)

    uniq = {}

    for c in accepted:
        key = (
            c["url"],
            c["price"],
            c.get("year")
        )

        if key not in uniq or c["score"] > uniq[key]["score"]:
            uniq[key] = c

    accepted = list(uniq.values())

    return accepted, rejected


def normalize_to_target_year(
    price: float,
    source_year: Optional[int],
    target_year: int
) -> float:

    if not source_year or source_year == target_year:
        return float(price)

    diff = source_year - target_year

    if diff > 0:
        return price * (0.95 ** diff)

    return price * (1.05 ** (-diff))


def weighted_median(values):
    if not values:
        return None

    arr = sorted(values, key=lambda x: x[0])

    total = sum(w for _, w in arr)

    acc = 0

    for value, weight in arr:
        acc += weight

        if acc >= total / 2:
            return value

    return arr[-1][0]


def robust_market(candidates: List[Dict[str, Any]]):
    if not candidates:
        return None

    enriched = []

    for c in candidates:
        adj = normalize_to_target_year(
            c["price"],
            c.get("year"),
            c["target_year"]
        )

        cc = dict(c)
        cc["adjusted_price"] = round(adj)

        enriched.append(cc)

    vals = [
        c["adjusted_price"]
        for c in enriched
    ]

    med = statistics.median(vals)

    abs_dev = [
        abs(x - med)
        for x in vals
    ]

    mad = (
        statistics.median(abs_dev)
        if abs_dev
        else 0
    )

    filtered = []
    outliers = []

    for c in enriched:
        p = c["adjusted_price"]

        ratio_ok = (
            med * 0.65
            <= p
            <= med * 1.35
        )

        mad_ok = (
            True
            if mad == 0
            else abs(p - med)
            <= max(3 * mad, med * 0.18)
        )

        if ratio_ok and mad_ok:
            filtered.append(c)

        else:
            cc = dict(c)
            cc["reason"] = "통계적 이상값"
            outliers.append(cc)

    if not filtered:
        filtered = enriched
        outliers = []

    wm = weighted_median([
        (
            c["adjusted_price"],
            max(1, c["score"])
        )
        for c in filtered
    ])

    prices = sorted(
        c["adjusted_price"]
        for c in filtered
    )

    if len(prices) >= 4:
        low = round(
            statistics.quantiles(
                prices,
                n=4,
                method="inclusive"
            )[0]
        )

        high = round(
            statistics.quantiles(
                prices,
                n=4,
                method="inclusive"
            )[2]
        )

    else:
        low = min(prices)
        high = max(prices)

    return {
        "count": len(filtered),
        "low": int(low),
        "high": int(high),
        "median": int(round(wm)),
        "prices": prices[:30],
        "adopted": sorted(
            filtered,
            key=lambda c: (
                -c["score"],
                abs(c["adjusted_price"] - wm)
            )
        )[:20],
        "outliers": outliers[:20],
    }


def calc_auction(
    v: Vehicle,
    market_mid: float
):
    d = 10.5
    km = v.km

    if km > 180000:
        d += 6

    elif km > 150000:
        d += 5

    elif km > 120000:
        d += 3

    elif km > 100000:
        d += 2

    elif km < 30000:
        d -= 1

    d += min(
        v.accident_count * 0.8,
        4
    )

    aa = v.accident_amount

    if aa >= 1200:
        d += 5

    elif aa >= 900:
        d += 4

    elif aa >= 700:
        d += 3

    elif aa >= 500:
        d += 2

    elif aa >= 300:
        d += 1

    p = v.parts_amount

    if p >= 700:
        d += 3.5

    elif p >= 500:
        d += 2.5

    elif p >= 300:
        d += 1.5

    elif p >= 150:
        d += 0.7

    d += v.uninsured
    d += v.use_history * 1.5
    d += v.frame * 3
    d += v.condition * 1.2
    d += v.liquidity * 1.5
    d += v.special * 1.5

    d = max(
        7,
        min(30, d)
    )

    auction = market_mid * (
        1 - d / 100
    )

    spread = max(
        50,
        auction * 0.045
    )

    low = round(
        (auction - spread) / 10
    ) * 10

    high = round(
        (auction + spread) / 10
    ) * 10

    target = round(
        auction / 10
    ) * 10

    upper = round(
        (auction + spread * 1.35) / 10
    ) * 10

    if target / market_mid >= .88:
        verdict = "매입 검토 가능"

    elif target / market_mid >= .82:
        verdict = "조건부 검토"

    else:
        verdict = "보수적 접근"

    return {
        "discount_rate": round(d, 1),
        "auction_low": int(low),
        "auction_high": int(high),
        "target": int(target),
        "upper": int(upper),
        "verdict": verdict,
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "provider": SEARCH_PROVIDER
        }
    )


@app.post("/api/analyze")
def analyze(v: Vehicle):
    queries = build_queries(v)

    web_results: List[Dict[str, str]] = []
    search_errors = []

    for q in queries:
        try:
            web_results.extend(
                search_web(q)
            )

        except Exception as e:
            search_errors.append(
                str(e)
            )

    web_results = dedupe_results(
        web_results
    )

    accepted, rejected = (
        extract_price_candidates(
            web_results,
            v
        )
    )

    for c in accepted:
        c["target_year"] = v.year

    if v.manual_prices:
        for x in v.manual_prices:
            if x and x > 0:
                accepted.append({
                    "price": float(x),
                    "year": v.year,
                    "score": 10,
                    "mileage": v.km,
                    "title": "수동 입력 가격",
                    "url": "",
                    "context": "사용자가 직접 입력한 유사매물 가격",
                    "reason": "채택",
                    "source_index": -1,
                    "target_year": v.year,
                })

    market = robust_market(
        accepted
    )

    if not market:
        return JSONResponse({
            "ok": False,
            "message":
                "자동 검색에서 신뢰할 만한 차량 판매가격을 충분히 찾지 못했어. "
                "차량명/트림을 더 정확히 입력하거나 유사매물 가격을 "
                "수동으로 3개 이상 입력해줘.",
            "queries": queries,
            "search_results": web_results[:12],
            "rejected": rejected[:20],
            "search_errors": search_errors,
        })

    auction = calc_auction(
        v,
        market["median"]
    )

    return {
        "ok": True,
        "queries": queries,
        "market": market,
        "auction": auction,
        "search_results": web_results[:12],
        "rejected": rejected[:20],
        "search_errors": search_errors,
    }
