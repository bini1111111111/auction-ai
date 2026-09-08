# 공매가 AI 4차 웹앱

## 기능
- 차량정보 입력
- 인터넷 검색 API 연동(선택)
- 검색 결과에서 '만원' 가격 자동 추출
- 이상값 제거 후 유사매물 중앙값 계산
- 사고/부품비/주행거리/자차미가입/용도/골격손상/시장성 반영
- 현실 공매가, 추천 입찰가, 절대 상한가 출력
- API 키가 없어도 수동 가격 입력으로 작동

## 로컬 실행
1. Python 3.10 이상 설치
2. 터미널에서 폴더로 이동
3. `pip install -r requirements.txt`
4. `uvicorn app:app --reload`
5. 브라우저에서 `http://127.0.0.1:8000`

## 인터넷 자동검색 켜기
### Brave Search API
환경변수:
- `SEARCH_PROVIDER=brave`
- `BRAVE_API_KEY=발급받은키`

### SerpAPI
환경변수:
- `SEARCH_PROVIDER=serpapi`
- `SERPAPI_KEY=발급받은키`

## Render 배포
1. GitHub에 이 폴더 업로드
2. Render에서 New > Blueprint 또는 Web Service
3. 저장소 연결
4. 환경변수에 SEARCH_PROVIDER와 API 키 입력
5. 배포

## 주의
- 이 버전은 검색엔진 결과의 제목/설명에서 가격 패턴을 추출하는 프로토타입이다.
- 엔카/KB차차차 등을 직접 무단 크롤링하지 않는다.
- 실제 업무용으로 쓰려면 공식/제휴 자동차 시세 API 또는 회사가 사용할 수 있는 데이터 공급원을 붙이는 것이 가장 안정적이다.
