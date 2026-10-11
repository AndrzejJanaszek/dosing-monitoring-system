import os
import json
import select
from pathlib import Path

def load_sender_paths():
    BASE_DIR = Path(__file__).resolve().parent
    sender_path_json = BASE_DIR / "sender-path.json"
    with open(sender_path_json, "r") as f:
        return json.load(f)

def open_ports(paths):
    fds = {}
    for p in paths:
        fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
        fds[p] = fd
    return fds

def close_ports(fds):
    for fd in fds.values():
        os.close(fd)

def ensure_log_dir():
    BASE_DIR = Path(__file__).resolve().parent
    log_dir = BASE_DIR / "receiver-logs"
    log_dir.mkdir(exist_ok=True)
    return log_dir

def main():
    paths_data = load_sender_paths()

    tank_paths = [t["slave_path"] for t in paths_data["tank_ports"]]
    signal_path = paths_data["signal_port"]["slave_path"]

    tank_fds = open_ports(tank_paths)
    signal_fd = open_ports([signal_path])[signal_path]

    log_dir = ensure_log_dir()
    tanks_log_path = log_dir / "tanks.log"
    signals_log_path = log_dir / "signals.log"

    print("Receiver started. Reading data...")

    try:
        while True:
            # monitoruj deskryptory - tylko do odczytu
            rlist, _, _ = select.select(list(tank_fds.values()) + [signal_fd], [], [])

            # Odczyt danych z tanków
            for path, fd in tank_fds.items():
                if fd in rlist:
                    try:
                        data = os.read(fd, 1024)
                        if data:
                            text = data.decode(errors="ignore").strip()
                            print(f"[TANK {path}] {text}")
                            with open(tanks_log_path, "a") as f:
                                f.write(text + "\n")
                    except OSError:
                        pass

            # Odczyt danych z sygnałów
            if signal_fd in rlist:
                try:
                    data = os.read(signal_fd, 4096)
                    if data:
                        text = data.decode(errors="ignore").strip()
                        print(f"[SIGNAL] {text}")
                        with open(signals_log_path, "a") as f:
                            f.write(text + "\n")
                except OSError:
                    pass

    except KeyboardInterrupt:
        print("Receiver stopped by user.")

    finally:
        close_ports(tank_fds)
        os.close(signal_fd)

if __name__ == "__main__":
    main()
