import os
import queue
import socket
import threading

HOST = "127.0.0.1"
PORT = 12345
DOWNLOAD_DIR = "client_downloads"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def send_line(sock, text):
    sock.sendall((text + "\n").encode())


def wait_event(events, expected):
    while True:
        kind, *data = events.get()
        if kind == "error":
            print(data[0])
            continue
        if kind == expected:
            return data
        if kind == "bcast":
            print(data[0])
            continue
        if kind == "info":
            print(data[0])
            continue


def receiver(sock, events, stop_event):
    buffer = bytearray()
    list_items = None

    while not stop_event.is_set():
        try:
            data = sock.recv(4096)
            if not data:
                break
            buffer.extend(data)

            while True:
                if list_items is not None:
                    nl = buffer.find(b"\n")
                    if nl == -1:
                        break
                    line = buffer[:nl].decode(errors="replace").rstrip("\r")
                    del buffer[:nl + 1]

                    if line == "RESP LIST_END":
                        events.put(("list", list_items))
                        list_items = None
                    elif line.startswith("RESP LIST_ITEM "):
                        list_items.append(line[15:])
                    elif line.startswith("RESP ERROR "):
                        events.put(("error", line[11:]))
                    elif line.startswith("BCAST "):
                        events.put(("bcast", line[6:]))
                    elif line.startswith("RESP "):
                        events.put(("info", line[5:]))
                    else:
                        events.put(("info", line))
                    continue

                nl = buffer.find(b"\n")
                if nl == -1:
                    break

                line = buffer[:nl].decode(errors="replace").rstrip("\r")
                del buffer[:nl + 1]

                if line == "RESP LIST_BEGIN":
                    list_items = []
                elif line.startswith("RESP LIST_ITEM "):
                    list_items = [line[15:]]
                elif line.startswith("RESP FILE "):
                    parts = line.split(" ", 3)
                    if len(parts) < 4:
                        events.put(("error", "Invalid file header"))
                        continue

                    filename = os.path.basename(parts[2])
                    size = int(parts[3])
                    path = os.path.join(DOWNLOAD_DIR, filename)

                    remaining = size
                    with open(path, "wb") as f:
                        while remaining > 0:
                            if buffer:
                                take = min(remaining, len(buffer))
                                f.write(buffer[:take])
                                del buffer[:take]
                                remaining -= take
                                continue

                            chunk = sock.recv(min(4096, remaining))
                            if not chunk:
                                remaining = -1
                                break
                            buffer.extend(chunk)

                    if remaining == 0:
                        events.put(("download_ok", filename, path))
                    else:
                        events.put(("error", f"Download gagal: {filename}"))
                elif line.startswith("RESP UPLOAD_OK "):
                    events.put(("upload_ok", line[15:]))
                elif line == "RESP OK":
                    events.put(("ok",))
                elif line.startswith("RESP ERROR "):
                    events.put(("error", line[11:]))
                elif line.startswith("BCAST "):
                    events.put(("bcast", line[6:]))
                else:
                    events.put(("info", line))

        except OSError:
            break

    stop_event.set()


def main():
    events = queue.Queue()
    stop_event = threading.Event()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, PORT))

    t = threading.Thread(target=receiver, args=(sock, events, stop_event), daemon=True)
    t.start()

    try:
        while not stop_event.is_set():
            try:
                cmd = input("> ").strip()
            except EOFError:
                break

            if not cmd:
                continue

            if cmd == "/list":
                send_line(sock, cmd)
                event = wait_event(events, "list")
                items = event[0]
                if items:
                    for item in items:
                        print(item)
                else:
                    print("Empty")

            elif cmd.startswith("/upload "):
                path = cmd.split(maxsplit=1)[1].strip()
                if not os.path.isfile(path):
                    print("File tidak ditemukan")
                    continue

                filename = os.path.basename(path)
                size = os.path.getsize(path)
                send_line(sock, f"/upload {filename} {size}")

                with open(path, "rb") as f:
                    while True:
                        chunk = f.read(4096)
                        if not chunk:
                            break
                        sock.sendall(chunk)

                event = wait_event(events, "upload_ok")
                print(f"Uploaded {event[0]}")

            elif cmd.startswith("/download "):
                filename = cmd.split(maxsplit=1)[1].strip()
                send_line(sock, f"/download {os.path.basename(filename)}")
                event = wait_event(events, "download_ok")
                print(f"Downloaded {event[0]}")

            elif cmd.startswith("/msg "):
                send_line(sock, cmd)
                wait_event(events, "ok")

            elif cmd == "/quit":
                send_line(sock, cmd)
                break

            else:
                send_line(sock, cmd)
                wait_event(events, "ok")

    finally:
        stop_event.set()
        try:
            sock.close()
        except OSError:
            pass


if __name__ == "__main__":
    main()