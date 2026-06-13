import os
import httpx
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Sparkling Studio Public Gateway & PWA")

# CORS को चालू रखना
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🌐 एनवायरनमेंट वेरिएबल्स (वर्सल या पब्लिक HF स्पेस की सेटिंग्स के लिए)
BACKEND_SERVER_URL = os.getenv("PRIVATE_BACKEND_URL", "https://Aryan-x-imgen-v3.hf.space")
IMGEN_API_KEY = os.getenv("IMGEN_API_KEY", "my_super_secure_default_key")

# 🔑 HF_TOKEN: प्राइवेट स्पेस को बाहर से एक्सेस करने के लिए बेहद ज़रूरी
HF_TOKEN = os.getenv("HF_TOKEN", "")

# स्टेटिक्स फोल्डर को माउंट करना
if os.path.exists("statics"):
    app.mount("/statics", StaticFiles(directory="statics"), name="statics")

# HTTPX का एसिंक क्लाइंट
async_client = httpx.AsyncClient(timeout=30.0)

class ImageRequestGateway(BaseModel):
    prompt: str
    user_negative: str = ""
    style_name: str = "Cinematic"
    ratio: str = "1:1"
    custom_width: int = 1024
    custom_height: int = 1024
    custom_seed: int = 0
    use_random: bool = True
    force_queue: bool = False

# 🛡️ हेडर जेनरेटर: इसमें हमारा कस्टम पासवर्ड और HF Token दोनों होंगे
def get_secure_headers():
    headers = {"X-API-Key": IMGEN_API_KEY}
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"
    return headers

# ==========================================
# 📱 PWA & STATIC ROUTING (मोबाइल ऐप सपोर्ट)
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    html_path = os.path.join("templates", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    elif os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>Error: index.html UI file not found in gateway!</h3>"

@app.get("/manifest.json")
async def serve_manifest():
    manifest_path = os.path.join("statics", "manifest.json")
    if os.path.exists(manifest_path):
        return FileResponse(manifest_path, media_type="application/json")
    return {"error": "manifest.json not found"}

@app.get("/sw.js")
async def serve_service_worker():
    sw_path = os.path.join("statics", "sw.js")
    if os.path.exists(sw_path):
        return FileResponse(sw_path, media_type="application/javascript")
    return {"error": "sw.js not found"}

# ==========================================
# 🛡️ API GATEWAY PROXY ENDPOINTS (सुरक्षा कवच)
# ==========================================

@app.post("/api/generate")
async def gateway_generate(req: ImageRequestGateway):
    url = f"{BACKEND_SERVER_URL.rstrip('/')}/api/generate"
    try:
        response = await async_client.post(url, json=req.dict(), headers=get_secure_headers())
        return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Backend communication error: {str(e)}")

@app.get("/api/status/{task_id}")
async def gateway_status(task_id: str):
    url = f"{BACKEND_SERVER_URL.rstrip('/')}/api/status/{task_id}"
    try:
        response = await async_client.get(url, headers=get_secure_headers())
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Task not found on backend")
        return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Backend communication error: {str(e)}")

@app.get("/api/queue")
async def gateway_queue():
    url = f"{BACKEND_SERVER_URL.rstrip('/')}/api/queue"
    try:
        response = await async_client.get(url, headers=get_secure_headers())
        return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Backend communication error: {str(e)}")

@app.get("/api/history")
async def gateway_history(skip: int = 0, limit: int = 10):
    url = f"{BACKEND_SERVER_URL.rstrip('/')}/api/history?skip={skip}&limit={limit}"
    try:
        response = await async_client.get(url, headers=get_secure_headers())
        return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Backend communication error: {str(e)}")

@app.delete("/api/history/{item_id}")
async def gateway_delete_history(item_id: str):
    url = f"{BACKEND_SERVER_URL.rstrip('/')}/api/history/{item_id}"
    try:
        response = await async_client.delete(url, headers=get_secure_headers())
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Item not found on backend")
        return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Backend communication error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
