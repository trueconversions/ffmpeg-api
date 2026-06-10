from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
import requests
import tempfile
import os
import json
import math

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

def write_cursor_png(path: str):
    import struct, zlib
    w, h = 24, 24
    shape = [
        "110000000000000000000000",
        "121000000000000000000000",
        "122100000000000000000000",
        "122210000000000000000000",
        "122221000000000000000000",
        "122222100000000000000000",
        "122222210000000000000000",
        "122222221000000000000000",
        "122222222100000000000000",
        "122222222210000000000000",
        "122222222221000000000000",
        "122222211111000000000000",
        "122222100000000000000000",
        "122212100000000000000000",
        "122102210000000000000000",
        "120002210000000000000000",
        "110000221000000000000000",
        "100000022100000000000000",
        "000000002210000000000000",
        "000000000110000000000000",
        "000000000000000000000000",
        "000000000000000000000000",
        "000000000000000000000000",
        "000000000000000000000000",
    ]
    color_map = {
        '1': (0, 0, 0, 255),
        '2': (255, 255, 255, 230),
        '0': (0, 0, 0, 0),
    }
    raw = b''
    for row in shape[:h]:
        raw += b'\x00'
        for char in row[:w]:
            raw += bytes(color_map.get(char, (0,0,0,0)))

    def chunk(tag, data):
        c = tag + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

    png = (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>II', w, h) + bytes([8, 6, 0, 0, 0]))
        + chunk(b'IDAT', zlib.compress(raw, 9))
        + chunk(b'IEND', b'')
    )
    with open(path, 'wb') as f:
        f.write(png)

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

        cursor_path = os.path.join(tmp, "cursor.png")
        write_cursor_png(cursor_path)

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
        fps = 24
        total_frames = math.ceil(duration * fps)

        scaled_h = int(img_h * out_w / img_w)
        scroll_dist = max(0, scaled_h - out_h)
        px_per_frame = scroll_dist / total_frames if total_frames > 0 else 0

        cursor_base_x = out_w // 2 + 180
        cursor_base_y = out_h // 2

        cursor_x_expr = (
            f"{cursor_base_x}"
            f"+sin(n*0.023)*40"
            f"+sin(n*0.051)*25"
            f"+sin(n*0.077)*15"
        )
        cursor_y_expr = (
            f"{cursor_base_y}"
            f"+sin(n*0.031)*35"
            f"+sin(n*0.059)*20"
            f"+sin(n*0.083)*12"
        )

        filter_str = (
            f"[0:v]scale={out_w}:-1,"
            f"crop={out_w}:{out_h}:0:'min(n*{px_per_frame},{scroll_dist})'[scrolled];"
            f"[2:v]scale=28:28[cursor];"
            f"[scrolled][cursor]overlay="
            f"x='{cursor_x_expr}':"
            f"y='{cursor_y_expr}'[out]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-framerate", str(fps), "-i", img_path,
            "-i", audio_path,
            "-loop", "1", "-framerate", str(fps), "-i", cursor_path,
            "-filter_complex", filter_str,
            "-map", "[out]",
            "-map", "1:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            output_path := os.path.join(tmp, req.output_filename)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise HTTPException(500, f"FFmpeg error: {result.stderr[-3000:]}")

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
