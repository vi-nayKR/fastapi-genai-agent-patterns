# 🤖 FastAPI & LangGraph Production Agent Patterns

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-Stateful_Supervisors-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-Distributed_Tracing-blueviolet.svg?logo=opentelemetry&logoColor=white)](https://opentelemetry.io)
[![MCP](https://img.shields.io/badge/MCP-JSON--RPC_2.0-purple.svg)](https://modelcontextprotocol.io/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A clean, production-grade reference architecture for building **stateful, observable Multi-Agent AI systems** using **Python FastAPI**, **LangGraph cyclic state machines**, **Model Context Protocol (MCP) tool servers**, and **OpenTelemetry distributed tracing**.

---

## 🏛️ Architecture & Agent Topology

```mermaid
graph TD
    User([User Request / API]) --> Supervisor[Supervisor Orchestrator]
    
    subgraph AgentSwarm["🤖 Specialized Agent Swarm"]
        Supervisor -->|Delegate Research| ResearchAgent[Research Agent]
        Supervisor -->|Delegate Code Exec| CodeAgent[Coding & Test Agent]
        Supervisor -->|Delegate Compliance| ComplianceAgent[Risk & Compliance Agent]
    end

    subgraph Checkpointing["💾 Persistent Memory & HITL"]
        PostgresCheckpointer[(PostgreSQL / Redis State Checkpointer)]
        Supervisor <--> PostgresCheckpointer
        HumanReview{Human In The Loop Approval required?}
        Supervisor -->|High-Risk Mutation| HumanReview
        HumanReview -->|Approved| Resume[Resume Execution Graph]
    end

    subgraph MCPServerGroup["🔌 Model Context Protocol Server"]
        CodeAgent -->|JSON-RPC 2.0| MCPServer[Custom MCP Tool Server]
        MCPServer --> DB[(Postgres / External APIs)]
    end
```

---

## ✨ Features Included

1. **Stateful Multi-Agent Supervisor Pattern:**
   - Typed graph states with dynamic worker delegation, loop prevention, and error escalation.
2. **Human-in-the-Loop (HITL) Checkpoints:**
   - Interrupt graph execution before sensitive database mutations, await human manager approval via REST API, and resume state without context loss.
3. **Model Context Protocol (MCP) Server:**
   - Out-of-the-box MCP server implementation exposing tools for SQL generation, API querying, and security validation.
4. **End-to-End OpenTelemetry Tracing:**
   - Automatic distributed trace injection linking HTTP requests, LLM token generations, tool invocations, and database queries.

---

## ⚡ Quickstart

```bash
git clone https://github.com/vi-nayKR/fastapi-genai-agent-patterns.git
cd fastapi-genai-agent-patterns

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

uvicorn src.main:app --host 0.0.0.0 --port 8002 --reload
```

---

## 👤 Author
**Vinay K R** — *Senior GenAI & Applied AI Systems Engineer*  
- 🌐 Portfolio: [portfolio.vinaykr.workers.dev](https://portfolio.vinaykr.workers.dev/)  
- 💼 LinkedIn: [linkedin.com/in/vi-naykr](https://linkedin.com/in/vi-naykr)  
- 🐙 GitHub: [github.com/vi-nayKR](https://github.com/vi-nayKR)  
