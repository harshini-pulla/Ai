import os
import logging
from typing import Dict, Any

from dotenv import load_dotenv
import httpx

from livekit import agents
from livekit.agents import AgentSession, Agent, JobContext, function_tool
from livekit.plugins import openai, silero

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] INTERVIEW_AGENT: %(message)s")

MCP_PORT = int(os.getenv("MCP_PORT", "8000"))
MCP_HOST = os.getenv("MCP_HOST", "http://localhost")
MCP_SERVER_URL = "https://mcp-server-qvqr.onrender.com/mcp"

class MCPHTTPClient:
    def __init__(self, url: str):
        self.url = url
        self.http: httpx.AsyncClient | None = None
        self.req_id = 0

    async def __aenter__(self):
        self.http = httpx.AsyncClient(timeout=20.0)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.http: await self.http.aclose()

    async def _rpc(self, method: str, params: Any = None) -> Any:
        if not self.http: raise ConnectionError("HTTP client not initialized.")
        self.req_id += 1
        payload = {"jsonrpc": "2.0", "id": self.req_id, "method": method, "params": params}
        resp = await self.http.post(self.url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data and data["error"]:
            raise RuntimeError(f"MCP error {data['error'].get('code')}: {data['error'].get('message')}")
        return data.get("result")

    async def call_tool(self, name: str, arguments: Dict[str, Any]):
        return await self._rpc("call_tool", {"name": name, "arguments": arguments or {}})

class InterviewAgent(Agent):
    def __init__(self, room_name: str = None):
        super().__init__(
            instructions = f"""
# Role
You are "Orion", a professional AI interviewer. You conduct structured interviews and provide fair evaluations.

# CRITICAL AUTOMATIC STARTUP
You are joining room: {room_name if room_name else '[ROOM_NAME]'}

IMMEDIATELY when you start:
1. Call `fetch_interview_context` with room name: {room_name if room_name else '[ROOM_NAME]'}
2. Once context is loaded successfully, begin the interview automatically
3. If context loading fails, ask candidate to confirm the room name and try again

# CONVERSATION FLOW RULES - EXTREMELY IMPORTANT
- **ASK ONLY ONE QUESTION AT A TIME**
- **WAIT FOR THE CANDIDATE'S COMPLETE RESPONSE BEFORE ASKING THE NEXT QUESTION**
- Never ask multiple questions in a single message
- Allow natural pauses for the candidate to think and respond
- Listen actively to their full answer before proceeding
- If they seem to be still speaking, wait for them to finish

# Interview Structure (only after context is loaded)
1. **Introduction & Consent** — Greet as Orion, confirm their name/email from the loaded context, ask permission to record and email transcript

2. **Resume Warmup (2-3 questions)** — Ask about background items from their uploaded resume to build rapport

3. **Core Competency Assessment (5-7 questions)** — Based on the job description, ask:
   - Situational questions ("Tell me about a time...")
   - Behavioral questions (STAR method)
   - Technical/domain questions relevant to the role

4. **Project Deep-Dive** — Pick one significant project from their resume:
   - Technical architecture and decisions
   - Measurable outcomes and impact
   - Challenges faced and solutions

5. **Role-Specific Focus** — Tailor questions to the job:
   - Sales: Pipeline, quotas, MEDDIC, objection handling
   - Technical: System design, coding practices, architecture
   - Leadership: Team management, decision making

6. **Candidate Questions & Wrap-up** — Ask about their questions, confirm contact info

# Evaluation Rubric (1-5 scale)
- Communication: Clarity and professionalism
- Role Fit: Match with job requirements  
- Technical/Domain Knowledge: Relevant expertise
- Problem Solving: Analytical approach
- Ownership: Accountability and initiative

# Important Guidelines
- Always be professional but conversational
- Ask follow-up questions for deeper insights
- Look for specific examples and measurable results
- Keep the interview focused and time-efficient
- Take mental notes for your final scorecard
- **REMEMBER: ONE QUESTION AT A TIME, WAIT FOR RESPONSE**

# End Process
When interview concludes, call `finish_and_email_transcript` with complete transcript, scorecard, and notes.

# STARTUP BEHAVIOR
Start immediately by calling fetch_interview_context, then begin the interview flow automatically.
"""
        )
        self._mcp_url = MCP_SERVER_URL
        self._interview_context = None
        self._transcript_log = []
        self._room_name = room_name
        self._context_loaded = False

    async def _call_mcp(self, tool_name: str, arguments: Dict[str, Any]):
        try:
            async with MCPHTTPClient(self._mcp_url) as mcp:
                return await mcp.call_tool(tool_name, arguments)
        except Exception as e:
            logging.error(f"MCP call failed for {tool_name}: {e}")
            return None

    @function_tool()
    async def fetch_interview_context(self, room_name: str) -> str:
        """Get current interview context (candidate info, JD, resume text)."""
        logging.info(f"Fetching context for room: {room_name}")
        result = await self._call_mcp("fetch_interview_context", {"room_name": room_name})
        
        if not result:
            return f"No interview context found for room '{room_name}'. Please ensure the candidate has filled out the form and the room name matches."
        
        # Store context for later use
        self._interview_context = result
        self._context_loaded = True
        
        # Provide a compact view for the LLM
        view = [
            f"✅ INTERVIEW CONTEXT LOADED",
            f"Room: {result.get('room_name')}",
            f"Candidate: {result.get('name')} <{result.get('email')}>",
            f"Phone: {result.get('phone', 'Not provided')}",
            f"Job Title: {result.get('job_title')}",
            f"Job Description: {result.get('job_description')[:500]}{'...' if len(result.get('job_description', '')) > 500 else ''}",
            f"Resume Summary (first 500 chars):",
            result.get('resume_text', '')[:500] + ('...' if len(result.get('resume_text', '')) > 500 else ''),
            "",
            "🎯 CONTEXT LOADED SUCCESSFULLY - NOW BEGIN THE INTERVIEW:",
            "1. Introduce yourself as Orion",
            f"2. Confirm you're speaking with {result.get('name')}",
            "3. Ask for recording consent",
            "4. Then proceed with the structured interview"
        ]
        return "\n".join(view)

    @function_tool()
    async def finish_and_email_transcript(self, room_name: str, transcript: str, scorecard: str = "", notes: str = "") -> str:
        """Send transcript to candidate & HR via Gmail MCP tool through MCP server."""
        logging.info(f"Finishing interview for room: {room_name}")
        
        result = await self._call_mcp("finish_and_email_transcript", {
            "room_name": room_name, 
            "transcript": transcript, 
            "scorecard": scorecard, 
            "notes": notes
        })
        
        if result:
            return f"✅ Interview completed! Emails sent successfully: {result}"
        else:
            return "❌ Failed to send emails. Please check the MCP server logs."

    def on_agent_speech_committed(self, message: str):
        """Log agent messages for transcript"""
        self._transcript_log.append(f"Interviewer: {message}")

    def on_user_speech_committed(self, message: str):
        """Log user messages for transcript"""
        self._transcript_log.append(f"Candidate: {message}")

async def entrypoint(ctx: JobContext):
    logging.info(f"🚀 Agent starting for room: {ctx.room.name}")
    await ctx.connect()
    
    # Enhanced session configuration
    session = AgentSession(
        stt=openai.STT(
            model="whisper-1", 
            prompt="You are transcribing a professional job interview. Use speaker tags 'Candidate:' and 'Interviewer:'. Format dates as YYYY-MM-DD and times as HH:MM. Be accurate with technical terms and company names."
        ),
        llm=openai.LLM(
            model="gpt-4o-mini",
            temperature=0.7,  # Slightly more conversational
        ),
        tts=openai.TTS(
            model="tts-1",
            voice="nova"  # Professional, clear voice
        ),
        vad=silero.VAD.load(),
    )
    
    # Pass room name to agent
    agent = InterviewAgent(room_name=ctx.room.name)
    
    # Add event listeners for transcript logging (synchronous callbacks)
    session.on("agent_speech_committed", agent.on_agent_speech_committed)
    session.on("user_speech_committed", agent.on_user_speech_committed)
    
    await session.start(room=ctx.room, agent=agent)
    logging.info("✅ Agent session started successfully")
    
    # Pre-check if context exists for this room (for logging purposes)
    try:
        room_name = ctx.room.name
        logging.info(f"🔍 Room started: {room_name}")
        logging.info("💡 Agent will automatically fetch context and begin interview")
            
    except Exception as e:
        logging.error(f"❌ Error in entrypoint setup: {e}")

if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))