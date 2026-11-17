# 클라우드(Google Cloud Run, 서울)용 이미지. 배포: scripts\deploy_cloudrun.ps1
# 자료는 이미지에 넣지 않는다: Cloud Storage 버킷을 /data 에 연결 (업체별 자료함·계정·설정).
FROM python:3.12-slim

# 토지이용계획 열람본 PDF 의 한글 글꼴 (landreport.py 가 /usr/share/fonts/truetype/nanum 을 찾는다)
RUN apt-get update && apt-get install -y --no-install-recommends fonts-nanum && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY web ./web
COPY samples ./samples

ENV PYTHONUNBUFFERED=1 \
    DEVELOGIC_MULTI=1 \
    DEVELOGIC_DATA=/data
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
