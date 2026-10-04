"""Fabrique la page « Coulisses » a partir de la trace reelle : python -m nexus_agents.render_html demo_out/trace.json out.html"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def render(trace_path: str, out_path: str) -> None:
    data = json.loads(Path(trace_path).read_text(encoding="utf-8"))
    tpl = (HERE / "templates" / "coulisses.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    Path(out_path).write_text(tpl.replace("/*__DATA__*/null", payload), encoding="utf-8")


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2])
