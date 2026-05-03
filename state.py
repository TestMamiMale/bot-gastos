import json
import os

STATE_FILE = "/tmp/bot_state.json"

def _load():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def _save(data):
    with open(STATE_FILE, "w") as f:
        json.dump(data, f)

def get_state(sender: str) -> dict:
    return _load().get(sender, {"step": "menu", "gasto": {}})

def set_state(sender: str, state: dict):
    all_states = _load()
    all_states[sender] = state
    _save(all_states)

def clear_state(sender: str):
    all_states = _load()
    if sender in all_states:
        del all_states[sender]
    _save(all_states)
