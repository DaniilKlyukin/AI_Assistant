import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import init_db, async_session, ChatMessage, SessionState
from app.core.agent import AIAgent
from app.core.config import settings

BASE_DIR = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AI_APP")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

agent = AIAgent()


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    temperature: float = 0.1
    top_p: float = 0.9
    max_iterations: int = 8


async def get_or_create_session_path(db: AsyncSession, session_id: str) -> Path:
    res = await db.execute(select(SessionState).where(SessionState.session_id == session_id))
    state = res.scalar_one_or_none()
    if not state:
        state = SessionState(session_id=session_id, current_path=str(settings.ROOT_FOLDER.resolve()))
        db.add(state)
        await db.commit()
        return settings.ROOT_FOLDER.resolve()
    return Path(state.current_path)


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    async with async_session() as db:
        try:
            current_path = await get_or_create_session_path(db, req.session_id)

            # Берем последние 40 записей, чтобы ассистент мог провести суммаризацию
            stmt = select(ChatMessage).where(ChatMessage.session_id == req.session_id).order_by(
                ChatMessage.created_at.desc()).limit(40)
            res = await db.execute(stmt)
            history = [
                {"role": m.role, "content": m.content, "tool_calls": m.tool_calls, "tool_call_id": m.tool_call_id,
                 "name": m.name}
                for m in reversed(res.scalars().all())
            ]

            ai_text, new_msgs, new_path = await agent.run_cycle(
                user_input=req.message,
                history=history,
                current_dir=current_path,
                temperature=req.temperature,
                top_p=req.top_p,
                max_iterations=req.max_iterations
            )

            if new_path:
                res_state = await db.execute(select(SessionState).where(SessionState.session_id == req.session_id))
                state = res_state.scalar_one()
                state.current_path = str(new_path.resolve())
                current_path = new_path

            # Сохраняем сообщение пользователя
            db.add(ChatMessage(session_id=req.session_id, role="user", content=req.message))

            # Сохраняем новые сообщения от ИИ и инструментов
            for m in new_msgs:
                db.add(ChatMessage(session_id=req.session_id, **m))

            await db.commit()

            return {"status": "success", "response": ai_text, "current_path": str(current_path.resolve())}
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/system/state/{session_id}")
async def get_state(session_id: str):
    async with async_session() as db:
        path = await get_or_create_session_path(db, session_id)
        return {"model": settings.MODEL, "current_path": str(path.resolve())}


@app.post("/api/system/clear-history")
async def clear_history(session_id: str):
    async with async_session() as db:
        await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
        await db.commit()
    return {"status": "ok"}


@app.get("/")
async def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="static")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)