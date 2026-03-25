import os
import select
import socket

HOST = "0.0.0.0"
PORT = 12345
BASE_DIR = "server_storage"

os.makedirs(BASE_DIR, exist_ok=True)


def send_line(sock, text):
    sock.sendall((text + "\n").encode())


def list_files():
    return sorted(os.listdir(BASE_DIR))


def close_client(sock, poller, fd_map, states):
    fd = sock.fileno()
    state = states.pop(sock, None)
    if state and state.get("upload"):
        try:
            state["upload"]["fh"].close()
        except OSError:
            pass
    try:
        poller.unregister(fd)
    except OSError:
        pass
    fd_map.pop(fd, None)
    try:
        sock.close()
    except OSError:
        pass


def broadcast(sender, message, poller, fd_map, states):
    dead = []
    for sock in list(states.keys()):
        try:
            send_line(sock, message)
        except OSError:
            dead.append(sock)

    for sock in dead:
        close_client(sock, poller, fd_map, states)


def process_buffer(sock, state, poller, fd_map, states):
    while True:
        upload = state.get("upload")
        if upload is not None:
            if not state["buffer"]:
                return

            take = min(upload["remaining"], len(state["buffer"]))
            upload["fh"].write(state["buffer"][:take])
            del state["buffer"][:take]
            upload["remaining"] -= take

            if upload["remaining"] == 0:
                upload["fh"].close()
                state["upload"] = None
                send_line(sock, f"RESP UPLOAD_OK {upload['filename']}")
                broadcast(sock, f"BCAST {upload['addr'][0]}:{upload['addr'][1]} uploaded {upload['filename']}", poller, fd_map, states)
            continue

        nl = state["buffer"].find(b"\n")
        if nl == -1:
            return

        line = state["buffer"][:nl].decode(errors="replace").rstrip("\r")
        del state["buffer"][:nl + 1]

        if line == "/list":
            files = list_files()
            send_line(sock, "RESP LIST_BEGIN")
            for name in files:
                send_line(sock, f"RESP LIST_ITEM {name}")
            send_line(sock, "RESP LIST_END")

        elif line.startswith("/upload "):
            parts = line.split(" ", 2)
            if len(parts) != 3:
                send_line(sock, "RESP ERROR Invalid upload command")
                continue

            filename = os.path.basename(parts[1])
            size = int(parts[2])
            path = os.path.join(BASE_DIR, filename)
            state["upload"] = {
                "filename": filename,
                "remaining": size,
                "fh": open(path, "wb"),
                "addr": state["addr"],
            }

        elif line.startswith("/download "):
            parts = line.split(" ", 1)
            if len(parts) != 2:
                send_line(sock, "RESP ERROR Invalid download command")
                continue

            filename = os.path.basename(parts[1])
            path = os.path.join(BASE_DIR, filename)

            if not os.path.exists(path):
                send_line(sock, "RESP ERROR File not found")
                continue

            size = os.path.getsize(path)
            send_line(sock, f"RESP FILE {filename} {size}")
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(4096)
                    if not chunk:
                        break
                    sock.sendall(chunk)

        elif line.startswith("/msg "):
            broadcast(sock, f"BCAST {state['addr'][0]}:{state['addr'][1]} {line[5:]}", poller, fd_map, states)
            send_line(sock, "RESP OK")

        elif line == "/quit":
            send_line(sock, "RESP OK")
            close_client(sock, poller, fd_map, states)
            return

        else:
            send_line(sock, "RESP ERROR Unknown command")


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()
    server.setblocking(False)

    poller = select.poll()
    poller.register(server, select.POLLIN)

    fd_map = {server.fileno(): server}
    states = {}

    while True:
        events = poller.poll()
        for fd, event in events:
            sock = fd_map.get(fd)
            if sock is None:
                continue

            if sock is server:
                conn, addr = server.accept()
                conn.setblocking(False)
                poller.register(conn, select.POLLIN)
                fd_map[conn.fileno()] = conn
                states[conn] = {
                    "buffer": bytearray(),
                    "upload": None,
                    "addr": addr,
                }
                continue

            if event & (select.POLLHUP | select.POLLERR):
                close_client(sock, poller, fd_map, states)
                continue

            try:
                data = sock.recv(4096)
                if not data:
                    close_client(sock, poller, fd_map, states)
                    continue
                states[sock]["buffer"].extend(data)
                process_buffer(sock, states[sock], poller, fd_map, states)
            except OSError:
                close_client(sock, poller, fd_map, states)


if __name__ == "__main__":
    main()