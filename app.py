import os,re,statistics,requests
from urllib.parse import urlparse
from fastapi import FastAPI,Request
from fastapi.responses import HTMLResponse,JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

app=FastAPI(title="공매가 AI 9.1")
templates=Jinja2Templates(directory="templates")

class Vehicle(BaseModel):
    car:str
    year:int
    km:int
    accident_count:int=0
    accident_amount:float=0
    parts_amount:float=0
    uninsured:str="없음"
    usage:str="일반"
    frame_damage:str="없음"
    condition:str="양호"
    marketability:str="보통"
    special_body:str="아님"
    manual_prices:str=""

def clean(s): return re.sub(r"\s+"," ",str(s or "")).strip()
def domain(u):
    try:return urlparse(u).netloc.replace("www.","")
    except:return ""
def prices(text):
    t=clean(text).replace(",","")
    out=[]
    for m in re.finditer(r"(?<!\d)(\d{3,5})\s*만\s*원?",t):
        n=int(m.group(1))
        if 200<=n<=20000: out.append(n)
    # 원 단위 표기
    for m in re.finditer(r"(?<!\d)(\d{7,9})\s*원",t):
        n=round(int(m.group(1))/10000)
        if 200<=n<=20000: out.append(n)
    return list(dict.fromkeys(out))

def years(text):
    now=2027
    vals=[]
    for x in re.findall(r"(?<!\d)(20\d{2})\s*년?(?:식|형)?",clean(text)):
        y=int(x)
        if 2000<=y<=now: vals.append(y)
    return vals

def mileages(text):
    t=clean(text).replace(",","")
    vals=[]
    for m in re.finditer(r"(?<!\d)(\d{1,6})\s*km",t,re.I):
        n=int(m.group(1))
        if 100<=n<=500000: vals.append(n)
    for m in re.finditer(r"주행(?:거리)?\s*[:\-]?\s*(\d{1,6})",t):
        n=int(m.group(1))
        if 100<=n<=500000: vals.append(n)
    return vals

def power(text):
    t=clean(text).lower()
    if "하이브리드" in t or "hev" in t:return "HEV"
    if "디젤" in t:return "DIESEL"
    if "lpg" in t or "lpi" in t:return "LPG"
    if "전기" in t or re.search(r"\bev\b",t):return "EV"
    if "가솔린" in t or "휘발유" in t:return "GAS"
    return ""

def facelift(text):
    t=clean(text).lower()
    if "더 뉴" in t:return "더뉴"
    if "디 올 뉴" in t:return "디올뉴"
    if "올 뉴" in t:return "올뉴"
    return ""

def drive(text):
    t=clean(text).upper().replace(" ","")
    if re.search(r"4WD|AWD|4륜|사륜|XDRIVE|4MATIC|QUATTRO",t):return "4WD"
    if re.search(r"2WD|2륜|FWD|RWD|전륜|후륜",t):return "2WD"
    return ""

TRIMS=["시그니처 그래비티","그래비티","캘리그래피","인스퍼레이션","시그니처","노블레스",
       "프레스티지","프리미엄 초이스","프리미엄","모던 플러스","모던","익스클루시브","럭셔리","스포츠","에어","어스"]
def trim(text):
    z=clean(text).replace(" ","").lower()
    for x in TRIMS:
        if x.replace(" ","").lower() in z:return x
    return ""

def list_page(text):
    t=clean(text)
    return bool(re.search(r"시세표|가격표|중고차\s*\d+\s*대|전체\s*매물|검색\s*결과",t,re.I))

def queries(v):
    c=clean(v.car)
    return [
      f'{v.year} {c} {v.km//10000}만km 중고차 가격',
      f'{v.year} {c} 중고차 {v.km}km',
      f'site:car.encar.com {v.year} {c}',
      f'site:kbchachacha.com {v.year} {c}',
      f'site:kcar.com {v.year} {c}',
      f'{v.year} {c} 인증중고차'
    ]

def brave(q):
    key=os.getenv("BRAVE_API_KEY","")
    if not key:return [],"BRAVE_API_KEY가 설정되지 않았어."
    try:
        r=requests.get("https://api.search.brave.com/res/v1/web/search",
            headers={"Accept":"application/json","X-Subscription-Token":key},
            params={"q":q,"count":10,"country":"KR","search_lang":"ko"},timeout=12)
        r.raise_for_status()
        rows=[]
        for x in r.json().get("web",{}).get("results",[]):
            rows.append({"title":clean(x.get("title")),"snippet":clean(x.get("description")),
                         "url":x.get("url",""),"source":domain(x.get("url",""))})
        return rows,""
    except Exception as e:return [],f"{type(e).__name__}: {e}"

def hard_reject(v,text):
    if list_page(text):return "목록/시세 페이지"
    tp,rp=power(v.car),power(text)
    if tp and rp and tp!=rp:return "동력원 불일치"
    tf,rf=facelift(v.car),facelift(text)
    if tf and rf and tf!=rf:return "세대/페이스리프트 불일치"
    if not tf and rf:return "세대/페이스리프트 불일치"
    return ""

def score(v,text,y,km):
    sc=20 # 검색 쿼리 자체가 모델명을 포함하므로 기본 모델 관련성
    tp,rp=power(v.car),power(text)
    if tp and rp==tp:sc+=15
    elif tp and not rp:sc+=5
    if y:
        d=abs(y-v.year); sc+=20 if d==0 else 12 if d==1 else 5 if d==2 else 0
    if km is not None:
        d=abs(km-v.km); sc+=20 if d<=10000 else 15 if d<=20000 else 10 if d<=30000 else 5 if d<=50000 else 0
    td,rd=drive(v.car),drive(text)
    if td and rd:sc+=8 if td==rd else 3
    tt,rt=trim(v.car),trim(text)
    if tt and rt:sc+=12 if tt==rt else 4
    elif tt and not rt:sc+=2
    return min(100,sc)

def adjust(v,p,y,km,text):
    x=float(p); notes=[]
    if y:
        dy=v.year-y
        if dy: x*=1+(0.035*dy); notes.append(f"연식 {dy:+d}년")
    if km is not None:
        dk=v.km-km
        pct=max(-0.10,min(0.10,-dk/100000*0.10))
        if abs(pct)>.001:x*=1+pct;notes.append(f"주행거리 {pct*100:+.1f}%")
    td,rd=drive(v.car),drive(text)
    if td and rd and td!=rd:
        pct=.03 if td=="4WD" else -.03
        x*=1+pct;notes.append(f"구동 {pct*100:+.1f}%")
    return round(x),", ".join(notes) or "보정 없음"

def risk_discount(v):
    d=.155
    d+=min(.06,v.accident_count*.008)
    d+=min(.05,v.accident_amount/10000*.03)
    d+=min(.03,v.parts_amount/10000*.02)
    if "있" in v.uninsured:d+=.015
    if v.usage!="일반":d+=.025
    if "있" in v.frame_damage:d+=.06
    if v.condition not in ("양호","좋음"):d+=.02
    if v.marketability=="낮음":d+=.025
    elif v.marketability=="높음":d-=.01
    if v.special_body!="아님":d+=.02
    return max(.10,min(.35,d))

@app.get("/",response_class=HTMLResponse)
def home(request:Request):return templates.TemplateResponse("index.html",{"request":request})

@app.post("/analyze")
def analyze(v:Vehicle):
    raw=[]; errors=[]
    for q in queries(v):
        rows,err=brave(q)
        if err:errors.append(err)
        raw.extend(rows)
        if len(raw)>=25:break

    # dedupe raw
    seen=set(); unique=[]
    for r in raw:
        k=((r["url"] or "").split("?")[0].rstrip("/"),r["title"])
        if k in seen:continue
        seen.add(k);unique.append(r)
    raw=unique

    extracted=[]; rejected=[]
    for r in raw:
        text=clean(r["title"]+" "+r["snippet"])
        ps=prices(text)
        ys=years(text); kms=mileages(text)
        if not ps:continue
        reason=hard_reject(v,text)
        for p in ps[:2]:
            row={**r,"price":p,"year":ys[0] if ys else None,"mileage":kms[0] if kms else None}
            if reason:
                row["reason"]=reason;rejected.append(row);continue
            row["score"]=score(v,text,row["year"],row["mileage"])
            if row["score"]<42:
                row["reason"]=f"유사도 낮음({row['score']}점)";rejected.append(row);continue
            row["adjusted_price"],row["adjustment"]=adjust(v,p,row["year"],row["mileage"],text)
            extracted.append(row)

    # manual prices are always explicit user comparables
    for x in re.findall(r"\d{3,5}",v.manual_prices.replace(",","")):
        p=int(x)
        if 200<=p<=20000:
            extracted.append({"title":"수동 비교매물","snippet":"","url":"","source":"manual",
             "price":p,"year":v.year,"mileage":v.km,"score":100,"adjusted_price":p,"adjustment":"수동 입력"})

    # dedupe calculation rows
    seen=set(); adopted=[]
    for x in sorted(extracted,key=lambda z:-z["score"]):
        k=(x.get("url"),x["price"])
        if k in seen:continue
        seen.add(k);adopted.append(x)
    adopted=adopted[:8]

    pipeline={
      "search_results":len(raw),
      "price_extracted":sum(1 for r in raw if prices(r["title"]+" "+r["snippet"])),
      "vehicle_info_detected":sum(1 for r in raw if years(r["title"]+" "+r["snippet"]) or mileages(r["title"]+" "+r["snippet"])),
      "candidate_count":len(extracted),"adopted":len(adopted),"rejected":len(rejected)
    }

    if not adopted:
        return {"status":"hold","message":"계산 가능한 비교매물을 확보하지 못했어.",
                "pipeline":pipeline,"adopted":[],"rejected":rejected[:20],"errors":list(dict.fromkeys(errors))}

    vals=[x["adjusted_price"] for x in adopted]
    lo,hi=min(vals),max(vals)
    spread=(hi-lo)/((hi+lo)/2)*100 if hi else 0
    if len(adopted)<=2 and spread>=15:
        return {"status":"spread_hold","message":"비교매물 수가 적고 가격 편차가 커서 공매가 산정을 보류했어.",
          "pipeline":pipeline,"adopted":adopted,"rejected":rejected[:20],
          "market_low":lo,"market_high":hi,"spread":round(spread,1),"errors":list(dict.fromkeys(errors))}

    # similarity-weighted mean
    weights=[max(.2,x["score"]/100) for x in adopted]
    retail=round(sum(x["adjusted_price"]*w for x,w in zip(adopted,weights))/sum(weights))
    disc=risk_discount(v)
    target=round(retail*(1-disc)/10)*10
    low=round(target*.95/10)*10; high=round(target*1.05/10)*10; upper=round(target*1.07/10)*10
    conf="높음" if len(adopted)>=4 and spread<15 else "보통" if len(adopted)>=3 and spread<20 else "낮음"
    return {"status":"ok","pipeline":pipeline,"adopted":adopted,"rejected":rejected[:20],
      "retail":retail,"discount":round(disc*100,1),"auction_low":low,"auction_high":high,
      "target":target,"upper":upper,"spread":round(spread,1),"confidence":conf,
      "errors":list(dict.fromkeys(errors))}

@app.exception_handler(Exception)
async def all_errors(request,exc):
    return JSONResponse(status_code=500,content={"status":"error","message":f"{type(exc).__name__}: {exc}"})
