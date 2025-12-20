import aiosqlite
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr
from typing import Dict, List, Optional
import json
import asyncio
from datetime import datetime
import bcrypt
import secrets

app = FastAPI()

class UserCredentials(BaseModel):
    email: EmailStr
    password: str

# === Улучшение 1: Асинхронная инициализация БД ===
DATABASE = "chat.db"

async def init_db():
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            verified INTEGER DEFAULT 0,
            verification_code TEXT
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY,
            chat_id TEXT NOT NULL,
            user_id INTEGER,
            text TEXT,
            timestamp TEXT NOT NULL,
            type TEXT DEFAULT 'text',
            image_data TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS reactions (
            id INTEGER PRIMARY KEY,
            message_id INTEGER,
            user_id INTEGER,
            emoji TEXT NOT NULL,
            FOREIGN KEY (message_id) REFERENCES messages (id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            UNIQUE(message_id, user_id, emoji)
        )''')
        await db.commit()

@app.on_event("startup")
async def startup():
    await init_db()

# === Улучшение 2: Асинхронные функции работы с БД ===
async def get_user_by_email(email: str) -> Optional[dict]:
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT id, password, verified FROM users WHERE email = ?", (email,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def get_user_id(email: str) -> Optional[int]:
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("SELECT id FROM users WHERE email = ?", (email,))
        row = await cursor.fetchone()
        return row[0] if row else None

async def save_message(chat_id: str, user_id: int, text: str, timestamp: str, msg_type: str = 'text', image_data: str = None) -> int:
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("""
            INSERT INTO messages (chat_id, user_id, text, timestamp, type, image_data)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (chat_id, user_id, text, timestamp, msg_type, image_data))
        await db.commit()
        return cursor.lastrowid

async def load_messages(chat_id: str) -> List[dict]:
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT m.id, m.chat_id, u.email, m.text, m.timestamp, m.type, m.image_data
            FROM messages m
            JOIN users u ON m.user_id = u.id
            WHERE m.chat_id = ?
            ORDER BY m.timestamp
        """, (chat_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def save_reaction(message_id: int, user_id: int, emoji: str) -> bool:
    async with aiosqlite.connect(DATABASE) as db:
        try:
            await db.execute("INSERT INTO reactions (message_id, user_id, emoji) VALUES (?, ?, ?)",
                           (message_id, user_id, emoji))
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

async def delete_reaction(message_id: int, user_id: int, emoji: str) -> bool:
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("""DELETE FROM reactions 
                                     WHERE message_id = ? AND user_id = ? AND emoji = ?""",
                                (message_id, user_id, emoji))
        await db.commit()
        return cursor.rowcount > 0

async def load_reactions(chat_id: str) -> Dict[str, Dict[str, List[str]]]:
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT m.timestamp, r.emoji, u.email
            FROM reactions r
            JOIN messages m ON r.message_id = m.id
            JOIN users u ON r.user_id = u.id
            WHERE m.chat_id = ?
        """, (chat_id,))
        reactions = {}
        async for row in cursor:
            timestamp, emoji, username = row["timestamp"], row["emoji"], row["email"]
            if timestamp not in reactions:
                reactions[timestamp] = {}
            if emoji not in reactions[timestamp]:
                reactions[timestamp][emoji] = []
            reactions[timestamp][emoji].append(username)
        return reactions

# === Раздача статики ===
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return FileResponse('static/index.html')

@app.get("/login")
async def login_page():
    return FileResponse('static/login.html')

@app.get("/register")
async def register_page():
    return FileResponse('static/register.html')

@app.get("/verify")
async def verify_page():
    return FileResponse('static/verify.html')

# === Улучшение 3: Потокобезопасное состояние чата ===
class ChatManager:
    def __init__(self):
        self.connections: Dict[str, List[WebSocket]] = {}
        self.users: Dict[str, Dict[str, WebSocket]] = {}  # chat_id -> {email: ws}
        self.typing: Dict[str, set] = {}

    async def connect(self, chat_id: str, email: str, websocket: WebSocket):
        await websocket.accept()
        # Удаляем пользователя из других чатов
        for cid, users in self.users.items():
            if email in users:
                await self.disconnect(cid, email, users[email])
        # Добавляем в новый чат
        self.connections.setdefault(chat_id, []).append(websocket)
        self.users.setdefault(chat_id, {})[email] = websocket
        self.typing.setdefault(chat_id, set())

    async def disconnect(self, chat_id: str, email: str, websocket: WebSocket):
        if chat_id in self.connections and websocket in self.connections[chat_id]:
            self.connections[chat_id].remove(websocket)
        if chat_id in self.users and email in self.users[chat_id]:
            del self.users[chat_id][email]
        if chat_id in self.typing and email in self.typing[chat_id]:
            self.typing[chat_id].discard(email)
        await self.broadcast_user_list(chat_id)
        await self.broadcast_typing(chat_id)

    async def broadcast(self, chat_id: str, message: dict):
        data = json.dumps(message)
        dead_connections = []
        for ws in self.connections.get(chat_id, []):
            try:
                await ws.send_text(data)
            except Exception:
                dead_connections.append(ws)
        # Очистка отвалившихся подключений
        for ws in dead_connections:
            for cid, connections in self.connections.items():
                if ws in connections:
                    connections.remove(ws)

    async def broadcast_user_list(self, chat_id: str):
        user_list = [{"username": user, "status": "online"} for user in self.users.get(chat_id, {})]
        await self.broadcast(chat_id, {
            "type": "user_list",
            "payload": {"users": user_list}
        })

    async def broadcast_typing(self, chat_id: str):
        typing_list = list(self.typing.get(chat_id, set()))
        await self.broadcast(chat_id, {
            "type": "typing_update",
            "payload": {"typing_users": typing_list}
        })

    async def add_typing(self, chat_id: str, email: str):
        self.typing.setdefault(chat_id, set()).add(email)
        await self.broadcast_typing(chat_id)

    async def remove_typing(self, chat_id: str, email: str):
        self.typing.get(chat_id, set()).discard(email)
        await self.broadcast_typing(chat_id)

manager = ChatManager()

# === Эндпоинты аутентификации (без изменений, но можно добавить JWT в будущем) ===
@app.post("/register")
async def register_user(credentials: UserCredentials):
    email = credentials.email
    password = credentials.password
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    code = secrets.token_hex(4).upper()
    async with aiosqlite.connect(DATABASE) as db:
        try:
            await db.execute("INSERT INTO users (email, password, verification_code) VALUES (?, ?, ?)",
                           (email, hashed, code))
            await db.commit()
            # В реальности: await send_verification_email(email, code)
            print(f"Код верификации для {email}: {code}")
            return {"message": "Регистрация успешна. Проверьте email."}
        except aiosqlite.IntegrityError:
            raise HTTPException(status_code=400, detail="Email уже существует")

@app.post("/verify")
async def verify_email(data: dict):
    email, code = data.get("email"), data.get("code")
    if not email or not code:
        raise HTTPException(status_code=400, detail="Email и код обязательны")
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("SELECT verification_code FROM users WHERE email = ? AND verified = 0", (email,))
        row = await cursor.fetchone()
        if row and row[0] == code:
            await db.execute("UPDATE users SET verified = 1, verification_code = NULL WHERE email = ?", (email,))
            await db.commit()
            return {"message": "Email подтверждён"}
        raise HTTPException(status_code=400, detail="Неверный код")

@app.post("/login")
async def login_user(credentials: UserCredentials):
    user = await get_user_by_email(credentials.email)
    if user and bcrypt.checkpw(credentials.password.encode('utf-8'), user['password'].encode('utf-8')):
        if not user['verified']:
            raise HTTPException(status_code=403, detail="Email не подтверждён")
        return {"message": "Успешный вход", "email": credentials.email}
    raise HTTPException(status_code=401, detail="Неверные учётные данные")

# === Улучшение 4: WebSocket с централизованным управлением ===
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    current_chat = None
    current_user = None

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type")
            payload = msg.get("payload", {})

            if msg_type == "join":
                email = payload.get("user")
                if not email:
                    await websocket.send_text(json.dumps({"type": "error", "message": "Email обязателен"}))
                    continue
                user_data = await get_user_by_email(email)
                if not user_data:
                    await websocket.send_text(json.dumps({"type": "error", "message": "Пользователь не найден"}))
                    continue
                if not user_data['verified']:
                    await websocket.send_text(json.dumps({"type": "error", "message": "Email не подтверждён"}))
                    continue
                current_user = email

            elif msg_type == "switch_chat" and current_user:
                new_chat = payload["chat_id"]
                if current_chat:
                    await manager.disconnect(current_chat, current_user, websocket)
                current_chat = new_chat
                await manager.connect(current_chat, current_user, websocket)

                # История
                messages = await load_messages(current_chat)
                await websocket.send_text(json.dumps({"type": "history", "payload": {"messages": messages}}))

                # Реакции
                reactions = await load_reactions(current_chat)
                for ts, emojis in reactions.items():
                    await websocket.send_text(json.dumps({
                        "type": "reactions_update", "payload": {"message_timestamp": ts, "reactions": emojis}
                    }))

                await manager.broadcast_user_list(current_chat)
                await manager.broadcast_typing(current_chat)

            elif msg_type == "send_message" and current_chat and current_user:
                text = payload.get("text", "").strip()
                if not text:
                    continue
                user_id = await get_user_id(current_user)
                timestamp = datetime.utcnow().isoformat()
                msg_id = await save_message(current_chat, user_id, text, timestamp)
                msg = {
                    "id": msg_id,
                    "chat_id": current_chat,
                    "user": current_user,
                    "text": text,
                    "timestamp": timestamp,
                    "type": "text"
                }
                await manager.broadcast(current_chat, {"type": "new_message", "payload": msg})

            elif msg_type == "add_reaction" and current_chat and current_user:
                msg_id = payload.get("message_id")
                emoji = payload.get("emoji")
                if msg_id and emoji:
                    user_id = await get_user_id(current_user)
                    if await save_reaction(msg_id, user_id, emoji):
                        await manager.broadcast(current_chat, {
                            "type": "reaction_added",
                            "payload": {"message_id": msg_id, "emoji": emoji, "username": current_user}
                        })

            elif msg_type == "remove_reaction" and current_chat and current_user:
                msg_id = payload.get("message_id")
                emoji = payload.get("emoji")
                if msg_id and emoji:
                    user_id = await get_user_id(current_user)
                    if await delete_reaction(msg_id, user_id, emoji):
                        await manager.broadcast(current_chat, {
                            "type": "reaction_removed",
                            "payload": {"message_id": msg_id, "emoji": emoji, "username": current_user}
                        })

            elif msg_type == "typing_start" and current_chat and current_user:
                await manager.add_typing(current_chat, current_user)

            elif msg_type == "typing_stop" and current_chat and current_user:
                await manager.remove_typing(current_chat, current_user)

            elif msg_type == "send_image" and current_chat and current_user:
                image_data = payload.get("image_data")
                if not image_data:
                    continue
                user_id = await get_user_id(current_user)
                timestamp = datetime.utcnow().isoformat()
                msg_id = await save_message(current_chat, user_id, "", timestamp, "image", image_data)
                msg = {
                    "id": msg_id,
                    "chat_id": current_chat,
                    "user": current_user,
                    "image_data": image_data,
                    "timestamp": timestamp,
                    "type": "image"
                }
                await manager.broadcast(current_chat, {"type": "new_message", "payload": msg})

    except WebSocketDisconnect:
        if current_chat and current_user:
            await manager.disconnect(current_chat, current_user, websocket)
