import threading


state = {
    "current_network": None,
}

lock = threading.Lock()
