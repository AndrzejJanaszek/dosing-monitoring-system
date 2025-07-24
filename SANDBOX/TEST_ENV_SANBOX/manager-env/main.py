import os
import pty
import json

NUM_SCALES = 2  # ile wag
CONFIG_PATH = "config.json"

def create_virtual_scale_ports(n):
    ports = []
    for i in range(n):
        master_fd, slave_fd = pty.openpty()
        slave_name = os.ttyname(slave_fd)
        ports.append({
            "id": i,
            "master_fd": master_fd,   # INT do zapisu w Programie 1
            "slave_path": slave_name  # STR do odczytu w Programie 2
        })
    return ports

def save_config(ports, signal_port):
    config = {
        "scales": ports,
        "signal": signal_port  # może być None albo drugi pty (jeśli potrzebujesz)
    }
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)

def main():
    print("[*] Tworzenie portów wag...")
    scale_ports = create_virtual_scale_ports(NUM_SCALES)

    signal_port = create_virtual_scale_ports(1)[0]

    print("[*] Zapis do config.json")
    save_config(scale_ports, signal_port)

    print("[*] Gotowe:")
    for port in scale_ports:
        print(f"  Waga {port['id']}: slave = {port['slave_path']}, master_fd = {port['master_fd']}")
    print(f"  Port sygnałowy: slave = {signal_port['slave_path']}, master_fd = {signal_port['master_fd']}")

if __name__ == "__main__":
    main()
