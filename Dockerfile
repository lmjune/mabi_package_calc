# 디스코드 봇 실행용 (Railway가 이 파일을 보고 자동으로 빌드해요)
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY bot/requirements.txt bot/requirements.txt
RUN pip install -r bot/requirements.txt

COPY . .

CMD ["python", "-m", "bot.main"]
