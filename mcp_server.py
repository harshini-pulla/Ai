import os
import io
import logging
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pdfminer.high_level import extract_text
from docx import Document
from datetime import datetime

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] MCP_INTERVIEW: %(message)s")

# Composio (optional for Gmail)
try:
    from composio import Composio
except Exception:
    Composio = None

COMPOSIO_API_KEY = os.getenv("COMPOSIO_API_KEY", "")
CONNECTED_ACCOUNT_ID_GMAIL = os.getenv("CONNECTED_ACCOUNT_ID_GMAIL", "")
HR_EMAIL = os.getenv("HR_EMAIL", "hr@example.com")
MCP_PORT = int(os.getenv("MCP_PORT", "8000"))
ALLOW_ORIGINS = os.getenv("MCP_CORS_ORIGINS", "*")

composio = None
if Composio and COMPOSIO_API_KEY:
    try:
        composio = Composio(api_key=COMPOSIO_API_KEY)
        logging.info("✅ Composio initialized for Gmail integration.")
    except Exception as e:
        logging.error(f"❌ Composio init error: {e}")
else:
    logging.warning("⚠️ Composio not configured — Gmail sends will be mocked.")

# In-memory store for context by room
room_context: Dict[str, Dict[str, Any]] = {}

def _send_gmail(to_email: str, subject: str, body: str) -> Dict[str, Any]:
    """Send email through composio Gmail tool or return a mock response."""
    if not composio or not CONNECTED_ACCOUNT_ID_GMAIL:
        logging.info(f"[MOCK-EMAIL] to={to_email} | subject={subject}")
        logging.info(f"[MOCK-BODY] {body[:200]}...")
        return {"success": True, "result": f"MOCKED: Email would be sent to {to_email}"}
    
    try:
        result = composio.tools.execute(
            "GMAIL_SEND_EMAIL",
            connected_account_id=CONNECTED_ACCOUNT_ID_GMAIL,
            arguments={
                "recipient_email": to_email, 
                "subject": subject, 
                "body": body
            },
        )
        logging.info(f"✅ Email sent successfully to {to_email}")
        return {"success": True, "result": result}
    except Exception as e:
        logging.error(f"❌ Gmail send error to {to_email}: {e}")
        return {"success": False, "error": str(e)}

def _extract_text_from_upload(filename: str, data: bytes) -> str:
    """Extract text from uploaded file based on file extension."""
    if not filename:
        return ""
    
    name = filename.lower()
    try:
        if name.endswith(".pdf"):
            with io.BytesIO(data) as fp:
                text = extract_text(fp)
                return text.strip()
        elif name.endswith(".docx"):
            with io.BytesIO(data) as fp:
                doc = Document(fp)
                paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
                return "\n".join(paragraphs)
        elif name.endswith((".txt", ".md")):
            return data.decode("utf-8", errors="ignore").strip()
        else:
            # Try to decode as text for other formats
            return data.decode("utf-8", errors="ignore").strip()
    except Exception as e:
        logging.error(f"Error extracting text from {filename}: {e}")
        return f"Error reading file: {str(e)}"

class InterviewMCP:
    async def initialize(self, _params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        logging.info("🔧 MCP Server initializing...")
        return {
            "protocolVersion": "0.1.0", 
            "serverInfo": {
                "name": "ai-interviewer-mcp",
                "version": "1.0.0"
            }
        }

    async def list_tools(self, _params: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "name": "fetch_interview_context",
                "description": "Fetch current room's interview context including candidate info, job description, and resume text.",
                "inputSchema": {
                    "type": "object", 
                    "properties": {
                        "room_name": {"type": "string", "description": "The LiveKit room name"}
                    }, 
                    "required": ["room_name"]
                },
            },
            {
                "name": "finish_and_email_transcript",
                "description": "Send interview transcript and evaluation to candidate and HR team via Gmail.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "room_name": {"type": "string", "description": "The LiveKit room name"},
                        "transcript": {"type": "string", "description": "Complete interview transcript with speaker tags"},
                        "scorecard": {"type": "string", "description": "Evaluation scorecard with 1-5 ratings"},
                        "notes": {"type": "string", "description": "Additional notes and recommendations"},
                    },
                    "required": ["room_name", "transcript"]
                },
            },
        ]

    async def call_tool(self, params: Dict[str, Any]) -> Any:
        name = params.get("name")
        arguments = params.get("arguments") or {}

        if name == "fetch_interview_context":
            room = arguments.get("room_name")
            if not room:
                raise ValueError("room_name is required")
            
            context = room_context.get(room)
            if not context:
                logging.warning(f"❌ No context found for room: {room}")
                return None
            
            logging.info(f"✅ Retrieved context for room: {room} (candidate: {context.get('name')})")
            return context

        elif name == "finish_and_email_transcript":
            room = arguments.get("room_name")
            transcript = arguments.get("transcript", "")
            scorecard = arguments.get("scorecard", "")
            notes = arguments.get("notes", "")
            
            if not room:
                raise ValueError("room_name is required")
            
            context = room_context.get(room, {})
            candidate_email = context.get("email")
            candidate_name = context.get("name", "Candidate")
            hr_email = context.get("hr_email") or HR_EMAIL
            job_title = context.get("job_title", "Position")
            
            if not candidate_email:
                logging.error(f"❌ No candidate email found for room: {room}")
                return {"success": False, "error": "Candidate email not found"}

            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
            
            # Email to candidate
            subject_candidate = f"Your Interview Transcript — {job_title} Interview"
            body_candidate = f"""Dear {candidate_name},

Thank you for taking the time to interview with us for the {job_title} position.

Please find your interview transcript below for your records:

=== INTERVIEW TRANSCRIPT ===
{transcript}

=== EVALUATION SUMMARY ===
{scorecard if scorecard else 'Evaluation pending'}

We appreciate your interest in joining our team. Our HR team will be in touch regarding next steps.

Best regards,
The Hiring Team

---
This interview was conducted by our AI interviewer "Orion" on {timestamp}
"""

            # Email to HR
            subject_hr = f"Interview Complete: {candidate_name} — {job_title}"
            body_hr = f"""CANDIDATE INTERVIEW SUMMARY

Candidate: {candidate_name}
Email: {candidate_email}
Phone: {context.get('phone', 'Not provided')}
Position: {job_title}
Interview Date: {timestamp}
Room: {room}

=== SCORECARD ===
{scorecard if scorecard else 'No scorecard provided'}

=== INTERVIEWER NOTES ===
{notes if notes else 'No additional notes'}

=== FULL TRANSCRIPT ===
{transcript}

=== CANDIDATE RESUME ===
{context.get('resume_text', 'Resume not available')[:2000]}...

---
Automatically generated by AI Interviewer System
"""

            # Send emails
            email_results = {}
            
            if candidate_email:
                candidate_result = _send_gmail(candidate_email, subject_candidate, body_candidate)
                email_results["candidate"] = candidate_result
                
            hr_result = _send_gmail(hr_email, subject_hr, body_hr)
            email_results["hr"] = hr_result

            logging.info(f"✅ Interview completed for {candidate_name}, emails dispatched")
            return {
                "success": True, 
                "room_name": room,
                "candidate": candidate_name,
                "emails_sent": email_results
            }

        else:
            raise ValueError(f"Unknown tool: {name}")

server_impl = InterviewMCP()
app = FastAPI(title="AI Interviewer MCP Server", version="1.0.0")

# Configure CORS
origins = ["*"] if ALLOW_ORIGINS == "*" else ALLOW_ORIGINS.split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "AI Interviewer MCP Server", "active_rooms": len(room_context)}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "active_interviews": len(room_context),
        "composio_configured": composio is not None
    }

@app.post("/mcp")
async def mcp_endpoint(request: Request):
    try:
        payload = await request.json()
        method = payload.get("method")
        params = payload.get("params")
        req_id = payload.get("id")
        
        logging.info(f"🔧 MCP Request: {method}")
        
        if method == "initialize":
            result = await server_impl.initialize(params)
        elif method == "list_tools":
            result = await server_impl.list_tools(params)
        elif method == "call_tool":
            result = await server_impl.call_tool(params or {})
        else:
            raise ValueError(f"Method not found: {method}")
            
        return JSONResponse(content={
            "jsonrpc": "2.0", 
            "id": req_id, 
            "result": result
        })
        
    except Exception as e:
        logging.error(f"❌ Error processing MCP request: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "jsonrpc": "2.0", 
                "id": req_id, 
                "error": {
                    "code": -32603, 
                    "message": str(e)
                }
            }
        )

# ---------- HTTP helpers for the frontend ----------

@app.post("/upload")
async def upload_resume(file: UploadFile = File(...)):
    """Upload and extract text from resume file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    
    try:
        data = await file.read()
        if len(data) == 0:
            raise HTTPException(status_code=400, detail="Empty file")
        
        text = _extract_text_from_upload(file.filename, data)
        
        if not text.strip():
            raise HTTPException(status_code=400, detail="Could not extract text from file")
        
        logging.info(f"✅ Resume uploaded: {file.filename} ({len(text)} chars)")
        return {
            "ok": True, 
            "text": text[:200000],  # Limit to 200k chars
            "filename": file.filename,
            "size": len(data)
        }
        
    except Exception as e:
        logging.error(f"❌ Resume upload error: {e}")
        raise HTTPException(status_code=500, detail=f"File processing error: {str(e)}")

@app.post("/context")
async def set_context(
    roomName: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    jobTitle: str = Form(""),
    jobDescription: str = Form(""),
    resumeText: str = Form(""),
    hrEmail: str = Form(""),
):
    """Set interview context for a specific room."""
    if not roomName or not name or not email:
        raise HTTPException(status_code=400, detail="roomName, name, and email are required")
    
    try:
        room_context[roomName] = {
            "room_name": roomName,
            "name": name,
            "email": email,
            "phone": phone,
            "job_title": jobTitle,
            "job_description": jobDescription,
            "resume_text": resumeText,
            "hr_email": hrEmail,
            "created_at": datetime.utcnow().isoformat(),
        }
        
        logging.info(f"✅ Context set for room: {roomName} (candidate: {name})")
        return {
            "ok": True, 
            "roomName": roomName,
            "candidate": name,
            "message": "Interview context saved successfully"
        }
        
    except Exception as e:
        logging.error(f"❌ Error setting context: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save context: {str(e)}")

@app.get("/context/{room_name}")
async def get_context(room_name: str):
    """Get interview context for debugging purposes."""
    context = room_context.get(room_name)
    if not context:
        raise HTTPException(status_code=404, detail="Room context not found")
    
    # Return sanitized version (without full resume text for brevity)
    return {
        "room_name": context.get("room_name"),
        "candidate": context.get("name"),
        "email": context.get("email"),
        "job_title": context.get("job_title"),
        "has_resume": bool(context.get("resume_text")),
        "created_at": context.get("created_at")
    }

@app.get("/rooms")
async def list_rooms():
    """List all active interview rooms."""
    return {
        "active_rooms": len(room_context),
        "rooms": [
            {
                "room_name": room,
                "candidate": data.get("name"),
                "job_title": data.get("job_title"),
                "created_at": data.get("created_at")
            }
            for room, data in room_context.items()
        ]
    }

if __name__ == "__main__":
    import uvicorn
    logging.info(f"🚀 Starting MCP Server on port {MCP_PORT}")
    uvicorn.run("mcp_server:app", host="0.0.0.0", port=MCP_PORT, reload=True)