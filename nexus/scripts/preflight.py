"""Contrôle avant installation : matériel, ports, Docker, GPU. Ne modifie rien.
Usage : python scripts/preflight.py"""
import ctypes, os, platform, shutil, socket, subprocess, sys

PORTS = {8000: "API + Dashboard", 11434: "Ollama", 5678: "n8n", 8080: "Baserow", 5173: "Vite (développement)"}


def ram_gb() -> float:
    try:
        if os.name == "nt":
            class M(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("p", ctypes.c_ulong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                            ("tpf", ctypes.c_ulonglong), ("apf", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
            m = M(); m.l = ctypes.sizeof(M); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)); return m.tp / 2**30
        with open("/proc/meminfo") as f:
            return int(f.readline().split()[1]) / 2**20
    except Exception:
        return 0.0


def gpu() -> str:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return "aucun GPU NVIDIA détecté"
    try:
        return subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True, timeout=10).stdout.strip() or "nvidia-smi sans sortie"
    except Exception as e:
        return f"nvidia-smi en erreur ({type(e).__name__})"


def port_free(p: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", p)) != 0


def docker_state() -> str:
    exe = shutil.which("docker")
    if not exe:
        return "docker introuvable"
    r = subprocess.run([exe, "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True, timeout=20)
    return f"démon actif, version {r.stdout.strip()}" if r.returncode == 0 else "client présent mais démon INACTIF (démarrer Docker Desktop)"


def recommend(ram: float, has_gpu: bool) -> str:
    if ram < 6:
        return "qwen2.5:1.5b-instruct (Apache-2.0) — qualité limitée, à mesurer ; ou ne pas lancer Ollama ici"
    if ram < 12 and not has_gpu:
        return "qwen2.5:3b-instruct est sous licence « qwen-research » : éviter pour un usage commercial. Préférer qwen2.5:7b-instruct en quantification 4 bits (Apache-2.0) si 8 Go libres, sinon qwen2.5:1.5b-instruct"
    return "qwen2.5:7b-instruct (Apache-2.0) ; mesurer ensuite avec scripts/bench_ollama.py avant de le retenir"


def main() -> int:
    ram = ram_gb()
    g = gpu()
    print(f"Système      : {platform.platform()}")
    print(f"Processeur   : {os.cpu_count()} cœurs logiques")
    print(f"Mémoire      : {ram:.1f} Go")
    print(f"GPU          : {g}")
    print(f"Disque libre : {shutil.disk_usage('.').free / 2**30:.0f} Go (prévoir 15 Go : images + modèle)")
    print(f"Docker       : {docker_state()}")
    bad = 0
    for p, what in PORTS.items():
        free = port_free(p)
        bad += 0 if free else 1
        print(f"Port {p:<6}  : {'libre' if free else 'OCCUPÉ'} — {what}")
    print(f"Modèle local suggéré : {recommend(ram, 'NVIDIA' in g or 'GeForce' in g or 'RTX' in g)}")
    print("Le choix final du modèle se fait sur mesure : python scripts/bench_ollama.py --models <liste>")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
