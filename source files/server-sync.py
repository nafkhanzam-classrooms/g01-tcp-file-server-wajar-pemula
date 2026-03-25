import os
import socket

HOST = "0.0.0.0"
PORT = 12345
BASE_DIR = "server_storage"

os.makedirs(BASE_DIR, exist_ok=True)


def send_line(conn, text):
    conn.sendall((text + "\n").encode())


def read_line(conn, buffer):
    while True:
        nl = buffer.find(b"\n")
        if nl != -1:
            line = buffer[:nl].decode(errors="replace").rstrip("\r")
            del buffer[:nl + 1]
            return line

        data = conn.recv(4096)
        if not data:
            return None
        buffer.extend(data)


def read_exact(conn, buffer, size):
    out = bytearray()
    while len(out) < size:
        if buffer:
            take = min(size - len(out), len(buffer))
            out.extend(buffer[:take])
            del buffer[:take]
            continue

        data = conn.recv(4096)
        if not data:
            return None
        buffer.extend(data)

    return bytes(out)


def list_files():
    return sorted(os.listdir(BASE_DIR))


def handle_client(conn):
    buffer = bytearray()

    try:
        while True:
            line = read_line(conn, buffer)
            if line is None:
                break

            if line == "/list":
                files = list_files()
                send_line(conn, "RESP LIST_BEGIN")
                for name in files:
                    send_line(conn, f"RESP LIST_ITEM {name}")
                send_line(conn, "RESP LIST_END")

            elif line.startswith("/upload "):
                parts = line.split(" ", 2)
                if len(parts) != 3:
                    send_line(conn, "RESP ERROR Invalid upload command")
                    continue

                filename = os.path.basename(parts[1])
                size = int(parts[2])
                data = read_exact(conn, buffer, size)
                if data is None:
                    break

                path = os.path.join(BASE_DIR, filename)
                with open(path, "wb") as f:
                    f.write(data)

                send_line(conn, f"RESP UPLOAD_OK {filename}")

            elif line.startswith("/download "):
                parts = line.split(" ", 1)
                if len(parts) != 2:
                    send_line(conn, "RESP ERROR Invalid download command")
                    continue

                filename = os.path.basename(parts[1])
                path = os.path.join(BASE_DIR, filename)

                if not os.path.exists(path):
                    send_line(conn, "RESP ERROR File not found")
                    continue

                size = os.path.getsize(path)
                send_line(conn, f"RESP FILE {filename} {size}")
                with open(path, "rb") as f:
                    while True:
                        chunk = f.read(4096)
                        if not chunk:
                            break
                        conn.sendall(chunk)

            elif line.startswith("/msg "):
                message = line[5:]
                send_line(conn, f"BCAST {message}")
                send_line(conn, "RESP OK")

            elif line == "/quit":
                send_line(conn, "RESP OK")
                break

            else:
                send_line(conn, "RESP ERROR Unknown command")

    except OSError:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(1)

        while True:
            conn, _ = server.accept()
            handle_client(conn)


if __name__ == "__main__":
    main()