"""First-run setup: pick a model tier, optionally download it, save the choice."""
import shutil
import subprocess

import ollama
import psutil
from rich.console import Console

from agent import config

console = Console()

LABELS = {"low": "Light", "mid": "Balanced", "high": "Strongest"}
RAM_HINT = {"low": "under 12 GB RAM", "mid": "12 to 20 GB RAM", "high": "20 GB RAM or more"}


def _installed() -> set | None:
    """Names of downloaded models, or None if Ollama cannot be reached."""
    try:
        listing = ollama.Client(host=config.OLLAMA_HOST).list()
        return {m.model for m in listing.models}
    except Exception:
        return None


def _ask(prompt: str) -> str:
    return console.input(prompt, markup=False).strip().lower()


def _choose_tier(recommended: str) -> str:
    tiers = list(config.TIERS)
    while True:
        answer = _ask(f"Your choice [1-{len(tiers)}, Enter = {tiers.index(recommended) + 1}]: ")
        if not answer:
            return recommended
        if answer.isdigit() and 1 <= int(answer) <= len(tiers):
            return tiers[int(answer) - 1]
        console.print(f"Please type a number from 1 to {len(tiers)}.")


def _download(model: str) -> None:
    if shutil.which("ollama") is None:
        console.print(f"The ollama command was not found. Install Ollama, then run: ollama pull {model}")
        return
    console.print(f"Downloading {model} (this can take a while)...")
    if subprocess.run(["ollama", "pull", model]).returncode != 0:
        console.print(f"The download failed. Retry later with: ollama pull {model}")


def run_wizard() -> bool:
    """Ask the user to pick a tier and save it. Returns True if it was saved."""
    detected = config.detect_tier()
    ram = psutil.virtual_memory().total / 1024**3

    console.print("\nAi-Agent setup\n", style="bold")
    console.print(f"Detected RAM: {ram:.0f} GB\n")
    for i, tier in enumerate(config.TIERS, 1):
        note = "   <- recommended for this device" if tier == detected else ""
        console.print(
            f"  {i}) {LABELS[tier]:<10}{config.TIERS[tier]:<14}{RAM_HINT[tier]}{note}",
            markup=False,
            highlight=False,
        )
    console.print()

    try:
        tier = _choose_tier(detected)
        model = config.TIERS[tier]

        installed = _installed()
        if installed is None:
            console.print(
                "Ollama is not reachable. Start it with: sudo systemctl enable --now ollama "
                "(or run: ollama serve)"
            )
        elif model not in installed and f"{model}:latest" not in installed:
            if _ask(f"{model} is not downloaded yet. Download it now? [Y/n] ") in ("", "y", "yes"):
                _download(model)
    except (KeyboardInterrupt, EOFError):
        console.print("\nSetup cancelled, nothing was saved.")
        return False

    config.save_settings({"tier": tier, "model": model})
    console.print(f"\nSaved: {LABELS[tier]} ({model}). Change it any time with: python main.py --setup")
    return True
