import os
import base64
from fastapi import FastAPI, Request
from fastapi.responses import Response, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import anthropic

app = FastAPI()

# 🔐 auth
USERNAME = os.environ.get("USERNAME", "admin")
PASSWORD = os.environ.get("PASSWORD", "mojegeslo")

def check_auth(auth_header: str):
    if not auth_header or not auth_header.startswith("Basic "):
        return False
    encoded = auth_header.split(" ")[1]
    decoded = base64.b64decode(encoded).decode("utf-8")
    username, password = decoded.split(":")
    return username == USERNAME and password == PASSWORD

@app.middleware("http")
async def basic_auth(request: Request, call_next):
    auth = request.headers.get("Authorization")

    if not check_auth(auth):
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": "Basic"},
            content="Unauthorized"
        )

    return await call_next(request)

# ostalo
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

class AdRequest(BaseModel):
    input: str
    mode: str
    pt_count: int = 1
    hl_count: int = 1

@app.get("/")
def root():
    return FileResponse("static/index.html")

@app.post("/generate")
def generate(req: AdRequest):
    if req.mode == "url":
        user_msg = f"Preberi to stran in ustvari Meta oglase: {req.input}"
    else:
        user_msg = f"Na podlagi tega opisa ustvari Meta oglase:\n\n{req.input}"

    prompt = f"""{user_msg}

Ustvari:
- {req.pt_count}x Primary Text
- {req.hl_count}x Headline
"""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    import json, re
    text = "".join(b.text for b in message.content if hasattr(b, "text"))
    match = re.search(r'\{[\s\S]*\}', text)
    return json.loads(match.group()) if match else {"error": "Napaka"}
