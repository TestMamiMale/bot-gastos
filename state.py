import json
import os

# Nombre del archivo donde se guardará la sesión de los usuarios
STATE_FILE = "state.json"

def _read_all_states():
    """Lee el archivo JSON con todos los estados."""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def _write_all_states(states):
    """Guarda el diccionario completo en el archivo JSON."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(states, f, indent=4, ensure_ascii=False)

def get_state(user_id):
    """Obtiene el estado de un usuario específico."""
    states = _read_all_states()
    return states.get(user_id, {})

def set_state(user_id, state_data):
    """Actualiza o crea el estado de un usuario."""
    states = _read_all_states()
    states[user_id] = state_data
    _write_all_states(states)

def clear_state(user_id):
    """Borra el estado de un usuario (reinicio)."""
    states = _read_all_states()
    if user_id in states:
        del states[user_id]
        _write_all_states(states)