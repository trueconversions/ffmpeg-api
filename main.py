from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
import requests
import tempfile
import os
import json

app = FastAPI()

SUPABASE_URL = "https://jxvhbfheblqiumklwhvd.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imp4dmhiZmhlYmxxaXVta2x3aHZkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MDkwMjU2OSwiZXhwIjoyMDk2NDc4NTY5fQ.-PviJdptQmsyasv7pwRENyaKt63ve1mhPkQDv60Jym0"

class RenderRequest(BaseModel):
    screenshot_url: str
    audio_url: str
    output_filename: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/render")
def render_video(req: RenderRequest):
    with tempfile.TemporaryDirectory() as tmp:
        img_path = os.path.join(tmp, "screenshot.jpg")
        r = requests.get(req.screenshot_url, timeout=60)
        if r.status_code != 200:
            raise HTTPException(500, f"Failed to download screenshot: {r.status_code}")
        with open(img_path, "wb") as f:
            f.write(r.content)

        audio_path = os.path.join(tmp, "audio.mp3")
        r = requests.get(req.audio_url, timeout=60)
        if r.status_code != 200:
            raise HTTPException(500, f"Failed to download audio: {r.status_code}")
        with open(audio_path, "wb") as f:
            f.write(r.content)

        probe_img = subprocess.run([
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", img_path
        ], capture_output=True, text=True)
        img_info = json.loads(probe_img.stdout)
        img_w = img_info["streams"][0]["width"]
        img_h = img_info["streams"][0]["height"]

        probe_audio = subprocess.run([
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", audio_path
        ], capture_output=True, text=True)
        audio_info = json.loads(probe_audio.stdout)
        duration = float(audio_info["format"]["duration"])

        out_w = 1920
        out_h = 1080
        scaled_h = int(img_h * (out_w / img_w))
        scroll_dist = max(0, scaled_h - out_h)

        output_path = os.path.join(tmp, req.output_filename)

        filter_complex = (
            f"[0:v]scale={out_w}:-1[scaled];"
            f"[scaled]crop={out_w}:{out_h}:0:'if(gte(t,{duration}),{scroll_dist},t/{duration}*{scroll_dist})'[cropped]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", img_path,
            "-i", audio_path,
            "-filter_complex", filter_complex,
            "-map", "[cropped]",
            "-map", "1:a",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-r", "24",
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            "-shortest",
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise HTTPException(500, f"FFmpeg error: {result.stderr[-2000:]}")

        with open(output_path, "rb") as f:
            video_data = f.read()

        upload_url = f"{SUPABASE_URL}/storage/v1/object/media/{req.output_filename}"
        headers = {
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "video/mp4",
            "x-upsert": "true"
        }
        up = requests.post(upload_url, headers=headers, data=video_data, timeout=120)
        if up.status_code not in (200, 201):
            raise HTTPException(500, f"Supabase upload failed: {up.status_code} {up.text}")

        public_url = f"{SUPABASE_URL}/storage/v1/object/public/media/{req.output_filename}"
        return {"video_url": public_url, "duration": duration, "image_size": f"{img_w}x{img_h}"}
