"""Download the OPUS-MT models and convert them to the CTranslate2 format.

Run once before building. The download is roughly 1.2 GB; the converted int8
output is about 300 MB, which is what ends up inside the installer.

    python scripts\\fetch_models.py

The conversion tools (torch, transformers) are heavy and are only needed here,
so they are installed into a throwaway virtual environment rather than into the
one the app runs in.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import venv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from local_pdf_translator.core.model_catalog import BUNDLED, REQUIRED_FILES

MODELS_DIR = REPO_ROOT / "models"
VENV_DIR = REPO_ROOT / "build" / "converter-venv"

# int8 roughly quarters the model size and runs faster on CPU, at a quality
# cost small enough not to be visible in ordinary prose.
QUANTISATION = "int8"

# torch is installed separately, from PyTorch's CPU-only index. The default
# PyPI wheel carries the whole CUDA runtime — about 2.5 GB — and every byte of
# it is dead weight here: the converter only ever reads weights off the
# checkpoint and writes them out again.
TORCH_REQUIREMENT = "torch"
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"

CONVERTER_REQUIREMENTS = [
    "ctranslate2>=4.0",
    "transformers>=4.30",
    "sentencepiece",
    "huggingface_hub",
]


def log(message: str) -> None:
    print(f"==> {message}", flush=True)


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def venv_executable(name: str) -> Path:
    directory = "Scripts" if sys.platform == "win32" else "bin"
    suffix = ".exe" if sys.platform == "win32" else ""
    return VENV_DIR / directory / f"{name}{suffix}"


def ensure_converter() -> None:
    if not VENV_DIR.exists():
        log("Creating a Python environment for the converter")
        VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
        venv.EnvBuilder(with_pip=True).create(VENV_DIR)

    log("Installing the conversion tools (this takes a while the first time)")
    python = venv_executable("python")
    subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=True
    )
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--quiet",
            TORCH_REQUIREMENT,
            "--index-url",
            TORCH_INDEX,
        ],
        check=True,
    )
    subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", *CONVERTER_REQUIREMENTS],
        check=True,
    )


def is_converted(directory: Path) -> bool:
    return all((directory / name).is_file() for name in REQUIRED_FILES)


def convert(repo: str, target: Path) -> None:
    log(f"Converting {repo} -> models/{target.name}")
    if target.exists():
        shutil.rmtree(target)

    converter = venv_executable("ct2-transformers-converter")
    subprocess.run(
        [
            str(converter),
            "--model",
            repo,
            "--output_dir",
            str(target),
            "--quantization",
            QUANTISATION,
            # The tokenizer models are not part of the CTranslate2 output but
            # the app needs them at runtime, so they are copied alongside.
            "--copy_files",
            "source.spm",
            "target.spm",
            "vocab.json",
            "tokenizer_config.json",
            "--force",
        ],
        check=True,
    )

    missing = [name for name in REQUIRED_FILES if not (target / name).is_file()]
    if missing:
        die(f"conversion of {repo} did not produce {', '.join(missing)}")


def directory_size(path: Path) -> str:
    total = sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    return f"{total / 1_000_000:.0f} MB"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="re-convert models that are already present"
    )
    arguments = parser.parse_args()

    pending = [
        model
        for model in BUNDLED
        if arguments.force or not is_converted(MODELS_DIR / model.directory_name)
    ]
    if not pending:
        log("Every model is already converted; nothing to do.")
        return 0

    ensure_converter()
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    for model in pending:
        convert(model.hugging_face_repo, MODELS_DIR / model.directory_name)

    log("Models ready:")
    for model in BUNDLED:
        directory = MODELS_DIR / model.directory_name
        print(f"    {model.directory_name:20s} {directory_size(directory):>8s}")

    print("\nNext: python scripts\\build_exe.py to build the application.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
