from fastapi import FastAPI
from pydantic import BaseModel
import subprocess
import requests
import os
import uuid
from supabase import create_client

app = FastAPI()

SUPABASE_URL = "https://jxvhbfheblqiumklwhvd.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imp4dmhiZmhlYmxxaXVta2x3aHZkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MDkwMjU2OSwiZXhwIjoyMDk2NDc4NTY5fQ.-PviJdptQmsyasv7pwRENyaKt63ve1mhPkQDv60Jym0"

class RenderRequest(BaseModel):
    screenshot_url: str
    audio_url: str

@app.post("/render")
async def render_video(req: RenderRequest):
    job_id = str(uuid.uuid4())
    screenshot_path = f"/tmp/{job_id}_screenshot.jpg"
    audio_path = f"/tmp/{job_id}_audio.mp3"
    output_path = f"/tmp/{job_id}_output.mp4"

    # Download files
    with open(screenshot_path, "wb") as f:
        f.write(requests.get(req.screenshot_url).content)
    with open(audio_path, "wb") as f:
        f.write(requests.get(req.audio_url).content)

    # Get image dimensions
    result = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0", screenshot_path
    ], capture_output=True, text=True)
    width, height = map(int, result.stdout.strip().split(","))

    # Get audio duration
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "csv=p=0", audio_path
    ], capture_output=True, text=True)
    duration = float(result.stdout.strip())

    # Calculate scroll speed (pixels per second)
    scroll_pixels = height - 1080
    scroll_speed = scroll_pixels / duration

    # Render with FFmpeg
    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", screenshot_path,
        "-i", audio_path,
        "-filter_complex",
        f"[0:v]scale={width}:-1,crop=1920:1080:0:'min(t*{scroll_speed},{height}-1080)'[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-c:a", "aac",
        "-shortest", "-pix_fmt", "yuv420p",
        "-r", "24",
        output_path
    ], check=True)

    # Upload to Supabase
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    filename = f"video_{job_id}.mp4"
    with open(output_path, "rb") as f:
        supabase.storage.from_("media").upload(filename, f, {"content-type": "video/mp4"})

    # Cleanup
    os.remove(screenshot_path)
    os.remove(audio_path)
    os.remove(output_path)

    return {
        "url": f"{SUPABASE_URL}/storage/v1/object/public/media/{filename}"
    }

@app.get("/health")
async def health():
    return {"status": "ok"}
