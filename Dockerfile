FROM jrottenberg/ffmpeg:4.4-alpine

RUN apk add --no-cache python3 py3-pip
RUN pip3 install fastapi uvicorn requests supabase

WORKDIR /app
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
