import os
import sqlite3
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import AsyncOpenAI
from duckduckgo_search import AsyncDDGS

# Configuration
PORT = 8000
DB_FILE = "brain_memory.db"
# Using your proxy mirror to bypass 403 error
PROXY_URL = "https://proxyapi.ru" 
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your-key-here")

app = FastAPI(title="Minecraft AI Brain")

# Initialize DB
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE,
            value TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS game_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            action TEXT,
            result TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# OpenAI Client configuration via Proxy
openai_client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    base_url=PROXY_URL
)

class GameState(BaseModel):
    player_hp: float
    player_max_hp: float
    player_food: int
    location: str
    inventory: str
    surrounding_blocks: str
    current_task: str
    last_chat_message: str

async def search_minecraft_wiki(query: str) -> str:
    """Async RAG tool to search for new Minecraft 26.2 mechanics via DuckDuckGo"""
    try:
        async with AsyncDDGS() as ddgs:
            # Narrowing search down specifically to Minecraft Java 26.2 updates
            search_query = f"Minecraft Java 26.2 patch notes mechanics {query}"
            results = await ddgs.text(search_query, max_results=3)
            if not results:
                return "No external data found."
            return "\n".join([f"- {r['title']}: {r['body']}" for r in results])
    except Exception as e:
        return f"Search temporarily unavailable: {str(e)}"

@app.post("/decide")
async def make_decision(state: GameState):
    # 1. Fetch short-term insights if something unknown is happening
    wiki_context = ""
    if "unknown" in state.current_task.lower() or "bug" in state.last_chat_message.lower():
        wiki_context = await search_minecraft_wiki(state.last_chat_message)

    # 2. Strict system prompt setup (forces Russian replies, coordinates reflexes/json)
    system_prompt = (
        "You are an advanced Minecraft Java Edition version 26.2 AI companion running on Java 25. "
        "Your task is to analyze the game state and issue strategic decisions. "
        "CRITICAL: You must talk to the player exclusively in RUSSIAN language. No English in chat answers! "
        "Format your output strictly as a JSON object with two fields: "
        "1. 'chat': what you say to the player in Russian. "
        "2. 'command': standard JSON command package for Baritone API / Fabric reflexes. "
        "Keep your responses sharp, helpful, and deeply integrated into the gameplay context."
    )

    user_content = f"""
    Current game environment specs:
    - Player HP: {state.player_hp}/{state.player_max_hp}
    - Food Level: {state.player_food}
    - Location coords: {state.location}
    - Inventory load: {state.inventory}
    - Blocks around: {state.surrounding_blocks}
    - Current focus: {state.current_task}
    - Last chat trigger: {state.last_chat_message}
    
    Additional RAG Context from updates:
    {wiki_context}
    """

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"},
            timeout=10.0
        )
        
        decision = response.choices[0].message.content
        
        # Log action to SQLite
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO game_logs (action, result) VALUES (?, ?)", (state.current_task, decision))
        conn.commit()
        conn.close()
        
        return {"status": "success", "decision": decision}

    except Exception as e:
        throw_msg = f"Brain processing failure: {str(e)}"
        raise HTTPException(status_code=500, detail=throw_msg)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
