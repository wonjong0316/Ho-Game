import asyncio
import math
import random
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
@app.get("/")
async def root():
    return {"status": "ok", "message": "호 게임 서버가 정상 작동 중입니다."}
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

CHARACTER_DATA = {
    '1': {"name": "인호 (광전사)", "hp": 110, "speed": 5, "dmg": 25, "color": "rgb(220, 20, 60)", "type": "melee"},
    '2': {"name": "승호 (좀도둑)", "hp": 70, "speed": 8, "dmg": 12, "color": "rgb(255, 215, 0)", "type": "vampire"},
    '3': {"name": "창호 (흑마법사)", "hp": 85, "speed": 5, "dmg": 18, "color": "rgb(138, 43, 226)", "type": "beam"},
    '4': {"name": "윤호 (마약왕)", "hp": 140, "speed": 2.5, "dmg": 15, "color": "rgb(255, 105, 180)", "type": "zone"},
    '5': {"name": "주호 (엘프)", "hp": 75, "speed": 7, "dmg": 15, "color": "rgb(0, 206, 209)", "type": "range"},
    '6': {"name": "연호 (암살자)", "hp": 65, "speed": 9, "dmg": 35, "color": "rgb(30, 30, 30)", "type": "ninja"},
    '7': {"name": "동호 (주짓떼로)", "hp": 130, "speed": 4.5, "dmg": 20, "color": "rgb(139, 69, 19)", "type": "throw"}
}

rooms = {}

# [수정] 몸통 박스끼리 닿았는지 확인하는 AABB 충돌 판정 함수
def is_touching(p, op):
    return (p["x"] < op["x"] + op["w"] and 
            p["x"] + p["w"] > op["x"] and 
            p["y"] < op["y"] + op["h"] and 
            p["y"] + p["h"] > op["y"])

def init_player(state, pid, char_id, start_x):
    c = CHARACTER_DATA[str(char_id)]
    w, h = (10, 50) if str(char_id) == '5' else (40, 40)
    state[pid].update({
        "x": start_x, "y": 300, "w": w, "h": h,
        "hp": c["hp"], "max_hp": c["hp"], 
        "color": c["color"], "name": c["name"], "dmg": c["dmg"], 
        "speed": c["speed"], "base_speed": c["speed"], "type": c["type"], 
        "cooldown": 0, "spin_timer": 0, "swing_timer": 0, "ninja_mode": 0, "keys": []
    })

def start_game(room):
    state = room["state"]
    if state.get("is_random"):
        c1, c2 = random.randint(1, 7), random.randint(1, 7)
    else:
        c1, c2 = state["p1"]["selection"], state["p2"]["selection"]
        
    init_player(state, "p1", c1, 150)
    init_player(state, "p2", c2, 600)
    state["effects"] = []
    state["blackout_timer"] = 0
    state["winner"] = None
    state["phase"] = "playing"

async def game_loop(room_id):
    while room_id in rooms and len(rooms[room_id]["players"]) > 0:
        room = rooms[room_id]
        state = room["state"]
        
        if state["phase"] == "playing":
            if state["blackout_timer"] > 0: state["blackout_timer"] -= 1

            for pid in ["p1", "p2"]: state[pid]["speed"] = state[pid]["base_speed"]
            for fx in state["effects"]:
                if fx["type"] == "zone":
                    for tid in ["p1", "p2"]:
                        if tid != fx["owner"]:
                            t = state[tid]
                            dist = math.hypot((t["x"]+t["w"]/2) - fx["x"], (t["y"]+t["h"]/2) - fx["y"])
                            if dist < 180:
                                t["hp"] -= 0.15
                                t["speed"] = t["base_speed"] * 0.3

            for pid in ["p1", "p2"]:
                p = state[pid]
                if p["hp"] <= 0: continue
                if p["cooldown"] > 0: p["cooldown"] -= 1
                if p["swing_timer"] > 0: p["swing_timer"] -= 1

                if p["spin_timer"] > 0:
                    p["spin_timer"] -= 1
                    continue
                
                keys = p.get("keys", [])
                if "UP" in keys and p["y"] > 0: p["y"] -= p["speed"]
                if "DOWN" in keys and p["y"] < 600 - p["h"]: p["y"] += p["speed"]
                if "LEFT" in keys and p["x"] > 0: p["x"] -= p["speed"]
                if "RIGHT" in keys and p["x"] < 800 - p["w"]: p["x"] += p["speed"]

                op_id = "p2" if pid == "p1" else "p1"
                op = state[op_id]
                
                if "ATTACK" in keys and p["cooldown"] == 0:
                    # [수정] 모든 근접 공격에 is_touching 판정 적용
                    if p["type"] == "melee":
                        p["swing_timer"] = 15
                        if is_touching(p, op): op["hp"] -= p["dmg"]
                        p["cooldown"] = 25
                    elif p["type"] == "vampire":
                        p["swing_timer"] = 15
                        if is_touching(p, op):
                            op["hp"] -= p["dmg"]
                            p["hp"] = min(p["max_hp"], p["hp"] + p["dmg"])
                        p["cooldown"] = 40
                    elif p["type"] in ["beam", "range"]:
                        dir_x = 14 if p["x"] < op["x"] else -14
                        state["effects"].append({"type": p["type"], "owner": pid, "x": p["x"]+p["w"]/2, "y": p["y"]+p["h"]/2, "vx": dir_x, "vy": 0, "life": 60, "color": p["color"], "dmg": p["dmg"]})
                        p["cooldown"] = 50 if p["type"] == "beam" else 20
                    elif p["type"] == "zone":
                        state["effects"].append({"type": "zone", "owner": pid, "x": p["x"]+p["w"]/2, "y": p["y"]+p["h"]/2, "vx": 0, "vy": 0, "life": 450, "color": "rgba(255,105,180,0.3)"})
                        p["cooldown"] = 150
                    elif p["type"] == "ninja":
                        if p["ninja_mode"] == 0:
                            state["blackout_timer"] = 60 # 1초 암전 (60프레임)
                            p["ninja_mode"] = 1
                            p["cooldown"] = 15 # 암전 발동 후 짧은 딜레이
                        else:
                            p["swing_timer"] = 15
                            if is_touching(p, op): op["hp"] -= p["dmg"]
                            p["ninja_mode"] = 0
                            p["cooldown"] = 120 # 무한 암전 방지를 위한 2초 쿨타임
                    elif p["type"] == "throw":
                        p["swing_timer"] = 15
                        if is_touching(p, op):
                            op["hp"] -= p["dmg"]
                            dx, dy = op["x"] - p["x"], op["y"] - p["y"]
                            op["x"] = max(0, min(800 - op["w"], p["x"] - dx))
                            op["y"] = max(0, min(600 - op["h"], p["y"] - dy))
                        p["cooldown"] = 45

            for fx in state["effects"][:]:
                if fx["type"] == "zone":
                    fx["life"] -= 1
                    if fx["life"] <= 0: state["effects"].remove(fx)
                else:
                    fx["x"] += fx["vx"]
                    fx["y"] += fx["vy"]
                    fx["life"] -= 1
                    tid = "p2" if fx["owner"] == "p1" else "p1"
                    t = state[tid]
                    # [수정] 투사체 충돌도 캐릭터의 폭(w), 높이(h)를 정확히 반영
                    if t["x"] < fx["x"] < t["x"] + t["w"] and t["y"] < fx["y"] < t["y"] + t["h"]:
                        t["hp"] -= fx.get("dmg", 0)
                        if fx["type"] == "beam": t["spin_timer"] = 150
                        if fx in state["effects"]: state["effects"].remove(fx)
                        continue
                    if fx["life"] <= 0 and fx in state["effects"]: state["effects"].remove(fx)

            if state["p1"]["hp"] <= 0: state["winner"] = "p2"; state["phase"] = "gameover"
            if state["p2"]["hp"] <= 0: state["winner"] = "p1"; state["phase"] = "gameover"

        for ws in list(room["players"].keys()):
            try: await ws.send_text(json.dumps({"type": "update", "state": state}))
            except: pass
        await asyncio.sleep(1/60)

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await websocket.accept()

    if room_id not in rooms:
        rooms[room_id] = {
            "players": {},
            "state": {
                "phase": "lobby", "is_random": False, "random_requester": None,
                "p1": {"selection": None, "rematch": False, "keys": []},
                "p2": {"selection": None, "rematch": False, "keys": []}
            },
            "task": None
        }

    room = rooms[room_id]
    if len(room["players"]) == 0: player_id = "p1"
    elif len(room["players"]) == 1: player_id = "p2"
    else: return await websocket.close(code=1000)

    room["players"][websocket] = player_id
    await websocket.send_text(json.dumps({"type": "init", "player_id": player_id}))

    if len(room["players"]) >= 1 and room["task"] is None:
        room["task"] = asyncio.create_task(game_loop(room_id))

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message["type"] == "input": room["state"][player_id]["keys"] = message["keys"]
            
            # [수정] 준비 완료 버튼 없이 선택 즉시 적용 및 랜덤 확인 로직 추가
            elif message["type"] == "select" and room["state"]["phase"] == "lobby":
                char_id = message["char"]
                if char_id == '0':
                    room["state"]["phase"] = "random_request"
                    room["state"]["random_requester"] = player_id
                else:
                    room["state"][player_id]["selection"] = char_id
                    if room["state"]["p1"]["selection"] and room["state"]["p2"]["selection"]:
                        room["state"]["is_random"] = False
                        start_game(room)
                        
            elif message["type"] == "random_response" and room["state"]["phase"] == "random_request":
                if message["accept"]:
                    room["state"]["is_random"] = True
                    start_game(room)
                else:
                    room["state"]["phase"] = "lobby"
                    room["state"]["p1"]["selection"] = None
                    room["state"]["p2"]["selection"] = None

            elif message["type"] == "rematch" and room["state"]["phase"] == "gameover":
                room["state"][player_id]["rematch"] = True
                if room["state"]["p1"]["rematch"] and room["state"]["p2"]["rematch"]:
                    room["state"]["p1"]["rematch"] = False
                    room["state"]["p2"]["rematch"] = False
                    start_game(room)
                    
            elif message["type"] == "to_lobby" and room["state"]["phase"] == "gameover":
                room["state"]["phase"] = "lobby"
                room["state"]["is_random"] = False
                room["state"]["random_requester"] = None
                for pid in ["p1", "p2"]: room["state"][pid].update({"rematch": False, "selection": None})

    except WebSocketDisconnect:
        del room["players"][websocket]
        if len(room["players"]) == 0:
            if room["task"]: room["task"].cancel()
            del rooms[room_id]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
