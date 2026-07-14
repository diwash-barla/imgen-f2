import os
import json
import base64
import httpx
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 🌟 PWA & API Gateway Setup (Stateless for Vercel)
app = FastAPI(title="Sparkling Studio Public Gateway", docs_url="/api-docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🌐 एनवायरनमेंट वेरिएबल्स
BACKEND_SERVER_URL = os.getenv("PRIVATE_BACKEND_URL", "https://Aryan-x-imgen-v3.hf.space").rstrip('/')
IMGEN_API_KEY = os.getenv("IMGEN_API_KEY", "my_super_secure_default_key")
HF_TOKEN = os.getenv("HF_TOKEN", "")

# ऑथेंटिकेशन हेडर (Private Space एक्सेस करने के लिए)
HEADERS = {"Authorization": f"Bearer {HF_TOKEN}"} if HF_TOKEN else {}

if os.path.exists("statics"):
    app.mount("/statics", StaticFiles(directory="statics"), name="statics")

class ImageRequestGateway(BaseModel):
    prompt: str
    user_negative: str = ""
    style_name: str = "Cinematic"
    ratio: str = "1:1"
    custom_seed: int = 0
    use_random: bool = True
    custom_width: int = 1024
    custom_height: int = 1024
    force_queue: bool = False

# ==========================================
# 📱 PWA & HTML ROUTING
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    for path in ["templates/index.html", "index.html"]:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    return "<h3>Error: index.html UI file not found!</h3>"

@app.get("/docs", response_class=HTMLResponse)
async def serve_docs_page():
    docs_path = os.path.join("templates", "docs.html")
    if os.path.exists(docs_path):
        with open(docs_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>Error: docs.html file not found!</h3>"

# ==========================================
# 🛡️ PURE REST API PROXY (100% Stateless)
# ==========================================
@app.post("/api/generate")
async def gateway_generate(req: ImageRequestGateway):
    url = f"{BACKEND_SERVER_URL}/call/generate"
    payload = {
        "data": [
            req.prompt, req.user_negative, req.style_name, 
            req.ratio, req.custom_seed, req.use_random, IMGEN_API_KEY
        ]
    }
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=HEADERS, timeout=15.0)
            if resp.status_code != 200:
                raise HTTPException(status_code=500, detail=f"Backend Error: {resp.text}")
                
            # Gradio API हमें एक event_id देता है, जिसे हम task_id बना रहे हैं
            event_id = resp.json().get("event_id")
            return {"status": "accepted", "task_id": event_id, "cached": False}
    except Exception as e:
        print(f"🔥 GATEWAY GENERATE ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/status/{task_id}")
async def gateway_status(task_id: str):
    url = f"{BACKEND_SERVER_URL}/call/generate/{task_id}"
    
    try:
        async with httpx.AsyncClient() as client:
            # Gradio के Live SSE Stream को पढ़ना 
            async with client.stream("GET", url, headers=HEADERS, timeout=5.0) as response:
                if response.status_code == 404:
                    return {"status": "failed", "error": "Task not found or expired"}
                
                current_event = None
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line: continue
                    
                    if line.startswith("event: "):
                        current_event = line.split("event: ")[1].strip()
                        
                    elif line.startswith("data: "):
                        data_str = line[6:]
                        
                        # 1. अगर काम चल रहा है, तो तुरंत लौट जाओ (Vercel को ब्लॉक न करें)
                        if current_event in ["generating", "pending"]:
                            return {"status": "processing"}
                            
                        # 2. अगर काम खत्म हो गया है, तो इमेज निकाल कर भेजो
                        elif current_event == "complete":
                            data_json = json.loads(data_str)
                            image_data = data_json[0]  # पहला आउटपुट इमेज है
                            seed = data_json[1]        # दूसरा आउटपुट सीड है
                            
                            # Gradio इमेज को URL के रूप में देता है, हमें उसे Base64 में बदलना होगा
                            if isinstance(image_data, dict) and "url" in image_data:
                                img_url = image_data["url"]
                                if not img_url.startswith("http"):
                                    img_url = BACKEND_SERVER_URL + img_url
                                
                                img_resp = await client.get(img_url, headers=HEADERS)
                                b64 = base64.b64encode(img_resp.content).decode("utf-8")
                                base64_final = f"data:image/png;base64,{b64}"
                            elif isinstance(image_data, str) and image_data.startswith("data:image"):
                                base64_final = image_data
                            else:
                                base64_final = ""
                                
                            return {"status": "completed", "image": base64_final, "seed": seed}
                            
                        # 3. अगर कोई एरर आ गया
                        elif current_event == "error":
                            return {"status": "failed", "error": "Backend generation error."}
                            
        # अगर स्ट्रीम खत्म हो जाए और कुछ न मिले
        return {"status": "processing"}
        
    except Exception as e:
        # अगर Vercel Timeout हो जाए, तो मतलब बैकएंड अभी भी काम कर रहा है
        return {"status": "processing"}

@app.get("/api/queue")
async def gateway_queue():
    # Vercel पर Queue का लाइव डेटा रखना संभव नहीं है, इसलिए Frontend के लिए डमी रिस्पॉन्स
    return {"status": "success", "data": []}

@app.get("/api/history")
async def gateway_history(skip: int = 0, limit: int = 10):
    url_post = f"{BACKEND_SERVER_URL}/call/history"
    payload = {"data": [skip, limit, IMGEN_API_KEY]}
    
    try:
        async with httpx.AsyncClient() as client:
            # 1. History माँगने की रिक्वेस्ट भेजो
            resp = await client.post(url_post, json=payload, headers=HEADERS, timeout=10.0)
            event_id = resp.json().get("event_id")
            
            # 2. History का डेटा निकालो (यह तुरंत आता है)
            url_get = f"{BACKEND_SERVER_URL}/call/history/{event_id}"
            async with client.stream("GET", url_get, headers=HEADERS) as response:
                current_event = None
                async for line in response.aiter_lines():
                    line = line.strip()
                    if line.startswith("event: "):
                        current_event = line.split("event: ")[1].strip()
                    elif line.startswith("data: "):
                        if current_event == "complete":
                            data_json = json.loads(line[6:])
                            return data_json[0] # यह हमारे Backend का असल History डेटा है
                            
    except Exception as e:
        print(f"🔥 HISTORY ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/history/{item_id}")
async def gateway_delete_history(item_id: str):
    return {"status": "success", "message": "Item deleted on frontend."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
