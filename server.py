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


@app.get("/stream")
def stream_music(q: str = Query(..., description="Song name in Bangla, Hindi, or English")):
    cmd_url = [
        "yt-dlp",
        "-f", "bestaudio",
        "--get-url",
        f"ytsearch1:{q} audio"
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
            async with websockets.connect(MCP_ENDPOINT, ping_interval=20, ping_timeout=20) as ws:
                print("Connected to Xiaozhi MCP Server!")
                async for message in ws:
                    data = json.loads(message)
                    msg_id = data.get("id")
                    method = data.get("method")

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
                                        "name": "play_youtube_song",
                                        "description": "Search and play ANY song from YouTube in Bangla, Hindi, or English. Always use this tool when the user asks to play a song or music.",
                                        "inputSchema": {
                                            "type": "object",
                                            "properties": {
                                                "song_name": {
                                                    "type": "string",
                                                    "description": "The exact name of the song and artist (in Bangla, Hindi, or English)"
                                                }
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
                        tool_name = params.get("name")
                        args = params.get("arguments", {})

                        if tool_name == "play_youtube_song":
                            song_name = args.get("song_name", "")
                            try:
                                title, artist = await asyncio.to_thread(search_youtube_info, song_name)
                                encoded_q = urllib.parse.quote(song_name)
                                stream_url = f"{RENDER_BASE_URL}/stream?q={encoded_q}"
                                result_text = (
                                    f"Found on YouTube: '{title}' by {artist}. "
                                    f"Stream URL: {stream_url} — Play this audio stream on the device now."
                                )
                            except Exception as e:
                                result_text = f"Could not fetch '{song_name}' from YouTube: {str(e)}"

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
