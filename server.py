import asyncio
import json
import random
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
app = FastAPI(title="Ô ăn quan online")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

QUAN = (0, 6)
P1_PITS = (1, 2, 3, 4, 5)
P2_PITS = (7, 8, 9, 10, 11)
START_BOARD = [0, 5, 5, 5, 5, 5, 0, 5, 5, 5, 5, 5]
ANIMATION_DELAY = 0.32

@dataclass
class Room:
    code: str
    board: list = field(default_factory=lambda: START_BOARD.copy())  # chỉ đếm quân dân
    quan_alive: list = field(default_factory=lambda: [True, True])  # quan trái, quan phải
    scores: list = field(default_factory=lambda: [0, 0])
    wins: list = field(default_factory=lambda: [0, 0])
    rps_choices: list = field(default_factory=lambda: [None, None])
    phase: str = "waiting"
    players: list = field(default_factory=lambda: [None, None])
    names: list = field(default_factory=lambda: ["Người chơi 1", "Người chơi 2"])
    sockets: list = field(default_factory=lambda: [None, None])
    turn: int = 0
    started: bool = False
    over: bool = False
    message: str = "Đang chờ người chơi thứ hai..."
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

rooms: Dict[str, Room] = {}

def room_code():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        code = "".join(random.choice(alphabet) for _ in range(5))
        if code not in rooms:
            return code

def legal_pits(side):
    return P1_PITS if side == 0 else P2_PITS

def occupied(board, quan_alive, idx):
    return board[idx] > 0 or (idx == 0 and quan_alive[0]) or (idx == 6 and quan_alive[1])

def game_over(room):
    return not any(room.quan_alive)

def finish_if_needed(room):
    if not game_over(room):
        return False
    for i in range(12):
        if i not in QUAN:
            room.scores[0 if i in P1_PITS else 1] += room.board[i]
        room.board[i] = 0
    room.over = True
    room.started = False
    room.phase = "over"
    if room.scores[0] == room.scores[1]:
        room.message = f"Ván hòa! Hai bên cùng {room.scores[0]} điểm."
    else:
        winner = 0 if room.scores[0] > room.scores[1] else 1
        room.wins[winner] += 1
        room.message = f"{room.names[winner]} thắng ván với {room.scores[winner]} điểm! Tổng số ván thắng: {room.wins[winner]}."
    return True

def calculate_move(board_in, quan_in, scores_in, side, pit, direction):
    """Tính nước đi và tạo các khung hình rải từng quân; quan là vật thể riêng, không biến thành dân."""
    board = board_in.copy()
    quan_alive = quan_in.copy()
    scores = scores_in.copy()
    frames = []
    stones = board[pit]
    board[pit] = 0
    pos = pit
    guard = 0
    message = ""
    while guard < 500:
        guard += 1
        while stones > 0:
            pos = (pos + direction) % 12
            board[pos] += 1
            stones -= 1
            frames.append({"board": board.copy(), "quan_alive": quan_alive.copy(), "phase": "sow"})
        nxt = (pos + direction) % 12
        if occupied(board, quan_alive, nxt):
            stones = board[nxt]
            board[nxt] = 0
            pos = nxt
            # Khi ô có quan nhưng không có dân, quan vẫn đứng đó; không thể bốc quan như dân.
            if stones == 0:
                break
            continue
        capture = (nxt + direction) % 12
        if occupied(board, quan_alive, capture):
            captured = board[capture]
            board[capture] = 0
            points = captured
            if capture == 0 and quan_alive[0]:
                points += 10
                quan_alive[0] = False
            elif capture == 6 and quan_alive[1]:
                points += 10
                quan_alive[1] = False
            scores[side] += points
            message = f"ăn {points} điểm"
            frames.append({"board": board.copy(), "quan_alive": quan_alive.copy(), "phase": "capture"})
            pos = capture
            while True:
                empty = (pos + direction) % 12
                target = (empty + direction) % 12
                if occupied(board, quan_alive, empty) or not occupied(board, quan_alive, target):
                    break
                captured = board[target]
                board[target] = 0
                points = captured
                if target == 0 and quan_alive[0]:
                    points += 10
                    quan_alive[0] = False
                elif target == 6 and quan_alive[1]:
                    points += 10
                    quan_alive[1] = False
                scores[side] += points
                message += f", ăn tiếp {points} điểm"
                frames.append({"board": board.copy(), "quan_alive": quan_alive.copy(), "phase": "capture"})
                pos = target
        break
    return {"board": board, "quan_alive": quan_alive, "scores": scores, "frames": frames, "message": message}

def do_seed(room, side):
    pits = legal_pits(side)
    if any(room.board[i] for i in pits):
        raise ValueError("Hàng của bạn vẫn còn quân.")
    for i in pits:
        room.board[i] = 1
    room.scores[side] -= 5
    room.message = f"{room.names[side]} nạ quân: nhận 5 quân, trừ 5 điểm."
    room.turn = 1 - side
    finish_if_needed(room)

def public_state(room, side):
    return {"type":"state", "code":room.code, "board":room.board, "quan_alive":room.quan_alive,
        "scores":room.scores, "names":room.names, "wins":room.wins, "turn":room.turn, "you":side,
        "started":room.started, "over":room.over, "phase":room.phase, "rps_choices":room.rps_choices,
        "message":room.message, "connected":[s is not None for s in room.sockets],
        "players":["Người chơi 1", "Người chơi 2"]}

async def send_state(room):
    for side, sock in enumerate(room.sockets):
        if sock:
            try:
                await sock.send_text(json.dumps(public_state(room, side), ensure_ascii=False))
            except Exception:
                pass

async def send_animation(room, frame, mover):
    for side, sock in enumerate(room.sockets):
        if sock:
            try:
                payload = public_state(room, side)
                payload.update({"type":"animation", "board":frame["board"], "quan_alive":frame["quan_alive"], "animating":True, "mover":mover})
                await sock.send_text(json.dumps(payload, ensure_ascii=False))
            except Exception:
                pass

@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/health")
async def health():
    return {"status":"ok", "message":"Máy chủ Ô ăn quan online đang hoạt động"}

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    room = None
    side = None
    try:
        while True:
            data = json.loads(await ws.receive_text())
            action = data.get("action")
            if action == "create":
                name = (data.get("name") or "Người chơi 1").strip()[:24] or "Người chơi 1"
                room = Room(code=room_code())
                rooms[room.code] = room
                side = 0
                room.sockets[0] = ws
                room.names[0] = name
                room.message = f"Phòng {room.code} đã tạo. Gửi mã cho người chơi thứ hai."
                await ws.send_text(json.dumps({"type":"joined", "code":room.code, "side":side}, ensure_ascii=False))
                await send_state(room)
            elif action == "join":
                code = (data.get("code") or "").strip().upper()
                target = rooms.get(code)
                if not target:
                    await ws.send_text(json.dumps({"type":"error", "message":"Không tìm thấy phòng. Kiểm tra lại mã phòng."}, ensure_ascii=False)); continue
                if target.sockets[1] is not None:
                    await ws.send_text(json.dumps({"type":"error", "message":"Phòng đã đủ hai người."}, ensure_ascii=False)); continue
                room = target; side = 1
                room.sockets[1] = ws
                room.names[1] = (data.get("name") or "Người chơi 2").strip()[:24] or "Người chơi 2"
                room.message = f"{room.names[1]} đã vào phòng. Chủ phòng có thể bắt đầu."
                await ws.send_text(json.dumps({"type":"joined", "code":room.code, "side":side}, ensure_ascii=False))
                await send_state(room)
            elif room is None:
                await ws.send_text(json.dumps({"type":"error", "message":"Hãy tạo phòng hoặc nhập mã phòng trước."}, ensure_ascii=False))
            elif action == "start":
                async with room.lock:
                    if side != 0:
                        await ws.send_text(json.dumps({"type":"error", "message":"Chỉ chủ phòng mới bắt đầu ván được."}, ensure_ascii=False)); continue
                    if not all(room.sockets):
                        await ws.send_text(json.dumps({"type":"error", "message":"Cần đủ hai người chơi mới bắt đầu."}, ensure_ascii=False)); continue
                    if room.started and not room.over:
                        await ws.send_text(json.dumps({"type":"error", "message":"Ván đang diễn ra rồi."}, ensure_ascii=False)); continue
                    room.board = START_BOARD.copy(); room.quan_alive = [True, True]
                    room.scores = [0, 0]; room.rps_choices = [None, None]; room.turn = 0
                    room.started = False; room.over = False; room.phase = "rps"
                    room.message = "Cả hai người hãy chọn kéo, búa hoặc bao để giành quyền đi trước."
                    await send_state(room)
            elif action == "choose_rps":
                async with room.lock:
                    choice = data.get("choice")
                    if side not in (0, 1) or choice not in ("keo", "bua", "bao"):
                        await ws.send_text(json.dumps({"type":"error", "message":"Lựa chọn kéo búa bao không hợp lệ."}, ensure_ascii=False)); continue
                    if room.phase != "rps":
                        await ws.send_text(json.dumps({"type":"error", "message":"Hiện không ở lượt kéo búa bao."}, ensure_ascii=False)); continue
                    room.rps_choices[side] = choice
                    if all(room.rps_choices):
                        a, b = room.rps_choices
                        beats = {"keo":"bao", "bua":"keo", "bao":"bua"}
                        if a == b:
                            room.rps_choices = [None, None]
                            room.message = "Hòa rồi! Cả hai hãy chọn kéo, búa hoặc bao lại nhé."
                        else:
                            room.turn = 0 if beats[a] == b else 1
                            room.started = True; room.over = False; room.phase = "playing"
                            room.message = f"{room.names[room.turn]} thắng kéo búa bao và được đi trước!"
                    else:
                        room.message = f"{room.names[side]} đã chọn. Đang chờ người chơi còn lại..."
                    await send_state(room)
            elif action == "move":
                async with room.lock:
                    try:
                        if not room.started or room.over or side != room.turn:
                            raise ValueError("Chưa đến lượt hoặc ván đã kết thúc.")
                        pit = int(data.get("pit"))
                        if pit not in legal_pits(side):
                            raise ValueError("Bạn chỉ được chọn ô dân thuộc hàng của mình.")
                        if room.board[pit] <= 0:
                            raise ValueError("Ô này không có quân dân để rải.")
                        visual_direction = 1 if data.get("direction") == "right" else -1
                        direction = visual_direction if side == 0 else -visual_direction
                        result = calculate_move(room.board, room.quan_alive, room.scores, side, pit, direction)
                        room.message = f"{room.names[side]} đang rải quân..."
                        for frame in result["frames"]:
                            await send_animation(room, frame, side)
                            await asyncio.sleep(ANIMATION_DELAY)
                        room.board = result["board"]
                        room.quan_alive = result["quan_alive"]
                        room.scores = result["scores"]
                        room.message = f"{room.names[side]} đã đi." + (" " + result["message"] + "!" if result["message"] else "")
                        room.turn = 1 - side
                        finish_if_needed(room)
                    except (ValueError, TypeError) as exc:
                        await ws.send_text(json.dumps({"type":"error", "message":str(exc)}, ensure_ascii=False)); continue
                    await send_state(room)
            elif action == "seed":
                async with room.lock:
                    try:
                        if not room.started or room.over or side != room.turn:
                            raise ValueError("Chưa đến lượt hoặc ván đã kết thúc.")
                        do_seed(room, side)
                    except ValueError as exc:
                        await ws.send_text(json.dumps({"type":"error", "message":str(exc)}, ensure_ascii=False)); continue
                    await send_state(room)
            elif action == "rematch":
                async with room.lock:
                    if not all(room.sockets):
                        await ws.send_text(json.dumps({"type":"error", "message":"Cần cả hai người còn kết nối để chơi ván mới."}, ensure_ascii=False)); continue
                    if not room.over:
                        await ws.send_text(json.dumps({"type":"error", "message":"Ván hiện tại chưa kết thúc."}, ensure_ascii=False)); continue
                    room.board = START_BOARD.copy(); room.quan_alive = [True, True]
                    room.scores = [0, 0]; room.rps_choices = [None, None]; room.turn = 0
                    room.started = False; room.over = False; room.phase = "rps"
                    room.message = "Ván mới đã sẵn sàng! Cả hai hãy kéo búa bao để chọn người đi trước."
                    await send_state(room)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        print(f"WebSocket error: {exc}")
    finally:
        if room is not None and side is not None and room.sockets[side] is ws:
            room.sockets[side] = None
            room.message = f"{room.names[side]} đã mất kết nối."
            await send_state(room)
            if not any(room.sockets):
                rooms.pop(room.code, None)
