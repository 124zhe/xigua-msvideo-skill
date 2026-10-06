"""Copy the three bundled Codex skills without replacing existing skills."""
import argparse
import os
from pathlib import Path
import shutil

SKILLS = ("xigua-msvideo-skill", "youtube-curiosity-stories", "youtube-ms-paint-images")
ROOT = Path(__file__).resolve().parents[1]


def default_destination():
    configured = os.environ.get("CODEX_HOME")
    codex_dir = Path(configured).expanduser() if configured else Path.home() / ".codex"
    return codex_dir / "skills"


def install(destination, dry_run=False):
    destination = Path(destination).expanduser().resolve()
    for name in SKILLS:
        if not (ROOT / "skills" / name / "SKILL.md").is_file():
            raise FileNotFoundError(f"Bundled skill is missing: {name}")
    conflicts = [name for name in SKILLS if os.path.lexists(destination / name)]
    if conflicts:
        raise FileExistsError("No skills were copied. Destination already contains: " + ", ".join(conflicts))
    targets = [destination / name for name in SKILLS]
    for name, target in zip(SKILLS, targets):
        print(f"{'Would install' if dry_run else 'Installing'} {name} -> {target}")
    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)
        for name, target in zip(SKILLS, targets):
            shutil.copytree(ROOT / "skills" / name, target,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    return targets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=default_destination())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        install(args.destination, args.dry_run)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{type(error).__name__}: {error}\n")
    if not args.dry_run:
        print("Installed. Reopen your Codex session and use $xigua-msvideo-skill.")


if __name__ == "__main__":
    main()
