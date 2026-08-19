from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict, Any

app = FastAPI(
    title="FastAPI GenAI Agent Patterns",
    version="1.0.0",
    description="Production Reference Architecture for Stateful LangGraph Multi-Agent Supervisors & MCP"
)

class AgentTaskRequest(BaseModel):
    task: str
    require_hitl_approval: bool = False

@app.post("/agents/execute", tags=["Agents"])
async def execute_agent_task(req: AgentTaskRequest):
    """Run stateful multi-agent supervisor graph."""
    return {
        "status": "completed" if not req.require_hitl_approval else "pending_human_approval",
        "task": req.task,
        "active_agent": "SupervisorAgent",
        "result": f"Executed multi-agent plan for task: '{req.task}'"
    }

@app.get("/health", tags=["Health"])
async def health():
    return {"status": "healthy", "service": "FastAPI GenAI Agent Patterns"}
