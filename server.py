import asyncio
import json
import os
import subprocess
import urllib.parse
import websockets
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
import uvicorn

app = FastAPI()

MCP_ENDPOINT = os.environ.get(
    "MCP_ENDPOINT",
    "wss://api.xiaozhi.me/mcp/?token=eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOjExNzY2NzEsImFnZW50SWQiOjI2NjAzNTgsImVuZHBvaW50SWQiOiJhZ2VudF8yNjYwMzU4IiwicHVycG9zZSI6Im1jcC1lbmRwb2ludCIsImlhdCI6MTc5NDY4NjE2OSwiZXhwIjoxODI2MjQzNzY5fQ.tjaILk8nkx554cRdJQyrbN5w_8EpKE5MJTiAgLJSoyHBz0dOOCO2IhnFOQZysaG86iNsXmmgtLWbcIG64RsoCQ"
)
RENDER_BASE_URL = "https://esp32-youtube-music-wvzk.onrender.com"


@app.get("/")
def home():
    return {"status": "SmartBuddy YouTube Music MCP Server is Running!"}


@app.get("/pcm")
def stream_pcm(q: str = Query(..., description="Song name"), rate: int = 24000):
    cmd_url = [
        "yt-dlp",
        "-f", "bestaudio",
        "--get-url",
        f"ytsearch1:{q} audio"
    ]
    try:
        audio_url = subprocess.check_output(cmd_url, text=True, timeout=15).strip().split('\n')[0]
    except Exception as e:
        return {"error": str(e)}

    # সরাসরি 16-bit Mono PCM অডিও আউটপুট (ESP32 I2S স্পিকারে সরাসরি বাজানোর জন্য)
    ffmpeg_cmd = [
        "ffmpeg",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-i", audio_url,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ac", "1",
        "-ar", str(rate),
        "-f", "s16le",
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

    return StreamingResponse(generate(), media_type="application/octet-stream")


def search_youtube_info(query: str):
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--no-playlist",
        f"ytsearch1:{query} audio"
    ]
    raw = subprocess.check_output(cmd, text=True, timeout=15)
    info = json.loads(raw.splitlines()[0])
    return info.get("title", query), info.get("uploader", "YouTube")


async def mcp_bridge_loop():
    while True:
        try:
            # ping_interval=None দিলে অযথা রিকানেক্ট লুপ হবে না
            async with websockets.connect(MCP_ENDPOINT, ping_interval=None, close_timeout=10) as ws:
                print("Connected to Xiaozhi MCP Server stably!")
                async for message in ws:
                    data = json.loads(message)
                    msg_id = data.get("id")
                    method = data.get("method")

                    if msg_id is None:
                        # Notifications (যেমন notifications/initialized) ইগনোর করা হবে
                        continue

                    if method == "initialize":
                        resp = {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": {
                                "protocolVersion": "2024-11-05",
                                "capabilities": {"tools": {}},
                                "serverInfo": {"name": "youtube-music-bridge", "version": "1.0.0"}
                            }
                        }
                        await ws.send(json.dumps(resp))

                    elif method == "tools/list":
                        resp = {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": {
                                "tools": [
                                    {
                                        "name": "search_youtube_song",
                                        "description": "Search any song on YouTube (Bangla, Hindi, English) and get its stream query.",
                                        "inputSchema": {
                                            "type": "object",
                                            "properties": {
                                                "song_name": {"type": "string"}
                                            },
                                            "required": ["song_name"]
                                        }
                                    }
                                ]
                            }
                        }
                        await ws.send(json.dumps(resp))

                    elif method == "tools/call":
                        params = data.get("params", {})
                        args = params.get("arguments", {})
                        song_name = args.get("song_name", "")
                        try:
                            title, artist = await asyncio.to_thread(search_youtube_info, song_name)
                            result_text = f"Found '{title}' by {artist}. Now call self.music.play_youtube with query='{song_name}' to play it on the ESP32 speaker!"
                        except Exception as e:
                            result_text = f"Search error: {str(e)}"

                        resp = {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": {
                                "content": [{"type": "text", "text": result_text}],
                                "isError": False
                            }
                        }
                        await ws.send(json.dumps(resp))
        except Exception as e:
            print(f"MCP reconnecting in 5s due to: {e}")
            await asyncio.sleep(5)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(mcp_bridge_loop())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
