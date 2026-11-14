
import subprocess
import os
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
import uvicorn

app = FastAPI()

@app.get("/")
def home():
    return {"status": "SmartBuddy YouTube Music Cloud Server is Running!"}

@app.get("/stream")
def stream_music(q: str = Query(..., description="Song name in Bangla, Hindi, or English")):
    cmd_url = [
        "yt-dlp",
        "-f", "bestaudio",
        "--get-url",
        f"ytsearch1:{q} official audio"
    ]
    try:
        audio_url = subprocess.check_output(cmd_url, text=True).strip().split('\n')[0]
    except Exception as e:
        return {"error": str(e)}

    ffmpeg_cmd = [
        "ffmpeg",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-i", audio_url,
        "-vn",
        "-acodec", "libmp3lame",
        "-ac", "1",
        "-ar", "24000",
        "-b:a", "64k",
        "-f", "mp3",
        "pipe:1"
    ]

    process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def generate():
        try:
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                yield chunk
        finally:
            process.kill()

    return StreamingResponse(generate(), media_type="audio/mpeg")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
