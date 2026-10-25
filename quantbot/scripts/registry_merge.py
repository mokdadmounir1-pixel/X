"""Reprend un registre d'essais produit sur un AUTRE ordinateur, uniquement s'il PROLONGE le registre du dépôt.

    python scripts/registry_merge.py <registry_du_pc.jsonl>

Conditions (sinon refus, rien n'est modifié) : chaîne de hachage intègre ; le registre du dépôt est un PRÉFIXE exact du registre reçu.
Ainsi les essais faits sur le PC s'ajoutent sans jamais réécrire l'historique, et aucun essai ne peut disparaître.
"""
import shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.lab.registry import TrialRegistry


def merge(incoming: Path, current: Path) -> str:
    inc, cur = TrialRegistry(incoming), TrialRegistry(current)       # lèvent si la chaîne est altérée
    a, b = [e["hash"] for e in cur.events()], [e["hash"] for e in inc.events()]
    if len(b) < len(a) or b[:len(a)] != a:
        raise SystemExit("REFUS : le registre reçu ne prolonge pas celui du dépôt (historique différent ou essais manquants)")
    if len(b) == len(a):
        return "Aucun nouvel essai : registre identique."
    shutil.copyfile(incoming, current)
    return f"Registre prolongé : {len(a)} -> {len(b)} événements ; essais comptés : {TrialRegistry(current).n_trials()}"


if __name__ == "__main__":
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]  # console cp1252 : jamais de crash d'affichage
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(merge(Path(sys.argv[1]), ROOT / "reports" / "registry.jsonl"))
