import os
import uuid
import base64
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from gradio_client import Client  # HTTPX की जगह अब यह HF Spaces से बात करेगा

# 🌟 PWA & API Gateway Setup
app = FastAPI(title="Sparkling Studio Public Gateway & PWA", docs_url="/api-docs")

# CORS चालू रखना
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🌐 एनवायरनमेंट वेरिएबल्स
BACKEND_SERVER_URL = os.getenv("PRIVATE_BACKEND_URL", "https://Dws321-Imgen-b2.hf.space")
IMGEN_API_KEY = os.getenv("IMGEN_API_KEY", "my_dumy_key")
HF_TOKEN = os.getenv("HF_TOKEN", "")

# स्टेटिक्स फोल्डर को माउंट करना
if os.path.exists("statics"):
    app.mount("/statics", StaticFiles(directory="statics"), name="statics")

class ImageRequestGateway(BaseModel):
    prompt: str
    user_negative: str = ""
    style_name: str = "Cinematic"
    ratio: str = "1:1"
    custom_seed: int = 0
    use_random: bool = True
    # Extra params (UI से आते हैं, लेकिन बैकएंड को ज़रूरत नहीं है)
    custom_width: int = 1024
    custom_height: int = 1024
    force_queue: bool = False

# ==========================================
# 🔌 GRADIO CLIENT & QUEUE MANAGER
# ==========================================
# Lazy Loading: ताकि स्टार्टअप के समय बैकएंड स्लीप मोड में हो तो गेटवे क्रैश न हो
_client = None
def get_client():
    global _client
    if _client is None:
        print("Gateway: Connecting to Backend Engine...")
        _client = Client(BACKEND_SERVER_URL, hf_token=HF_TOKEN)
    return _client

# इन-मेमोरी टास्क मैनेजर (Frontend के Task Polling को संभालने के लिए)
active_tasks = {}

# ==========================================
# 📱 PWA & HTML ROUTING (UI & Docs)
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

@app.get("/docs", response_class=HTMLResponse)
async def serve_docs_page():
    docs_path = os.path.join("templates", "docs.html")
    if os.path.exists(docs_path):
        with open(docs_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>Error: docs.html file not found in templates folder!</h3>"

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
# 🛡️ API GATEWAY PROXY ENDPOINTS
# ==========================================
@app.post("/api/generate")
async def gateway_generate(req: ImageRequestGateway):
    try:
        client = get_client()
        # .submit() बैकग्राउंड में रिक्वेस्ट भेजकर तुरंत एक Job ऑब्जेक्ट रिटर्न करता है
        job = client.submit(
            req.prompt, 
            req.user_negative, 
            req.style_name, 
            req.ratio, 
            req.custom_seed, 
            req.use_random, 
            IMGEN_API_KEY, 
            api_name="/generate"
        )
        task_id = str(uuid.uuid4())
        active_tasks[task_id] = job
        
        # Frontend को वही पुराना response दे रहे हैं जिसकी उसे आदत है
        return {"status": "accepted", "task_id": task_id, "cached": False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backend communication error: {str(e)}")

@app.get("/api/status/{task_id}")
async def gateway_status(task_id: str):
    if task_id not in active_tasks:
        raise HTTPException(status_code=404, detail="Task not found or expired")
    
    job = active_tasks[task_id]
    try:
        status_info = job.status()
        status_name = status_info.code.name # PENDING, STARTING, PROCESSING, FINISHED, FAILED
        
        if status_name in ["PENDING", "STARTING", "PROCESSING"]:
            return {"status": "processing"}
            
        elif status_name == "FINISHED":
            # जब इमेज बन जाती है, तो Gradio Client उसे टेम्परेरी फोल्डर में डाउनलोड कर लेता है
            outputs = job.outputs()
            image_filepath = outputs[0]
            seed = outputs[1]
            
            # Frontend को Base64 चाहिए, तो हम इमेज पढ़कर कन्वर्ट कर देंगे
            with open(image_filepath, "rb") as f:
                encoded_string = base64.b64encode(f.read()).decode('utf-8')
                base64_final = f"data:image/png;base64,{encoded_string}"
            
            # मेमोरी साफ़ करना
            del active_tasks[task_id]
            
            return {"status": "completed", "image": base64_final, "seed": seed}
            
        elif status_name == "FAILED":
            del active_tasks[task_id]
            return {"status": "failed", "error": "Generation failed on the backend engine."}
            
    except Exception as e:
        return {"status": "failed", "error": str(e)}

@app.get("/api/history")
async def gateway_history(skip: int = 0, limit: int = 10):
    try:
        client = get_client()
        # .predict() वेट (block) करता है और सीधा रिजल्ट देता है (History के लिए परफेक्ट है)
        response = client.predict(skip, limit, IMGEN_API_KEY, api_name="/history")
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backend communication error: {str(e)}")

@app.get("/api/queue")
async def gateway_queue():
    # Frontend को खुश रखने के लिए एक डमी (Dummy) Queue Response
    return {
        "status": "success", 
        "data": [{"task_id": k, "status": "processing"} for k in active_tasks.keys()]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
