#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 infan
# Autor: infan
#
# Este archivo forma parte del proyecto "organizar_anime".
# Se distribuye bajo la GNU Affero General Public License v3.0 o posterior.

import argparse
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".ts", ".m4v"}
INVALID_FS_CHARS = r'<>:"/\|?*'


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def safe_name(text: str) -> str:
    cleaned = text
    for ch in INVALID_FS_CHARS:
        cleaned = cleaned.replace(ch, "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or "SinNombre"


def normalize_for_match(text: str) -> str:
    text = strip_accents(text).lower()
    text = re.sub(r"[-_]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


MONOSCHINOS_EPISODE_RE = re.compile(
    r"^Ver\s+episodio\s+(\d+)\s+de\s+(.+?)\s*-\s*MonosChinos$",
    re.IGNORECASE,
)
MONOSCHINOS_MOVIE_RE = re.compile(
    r"^Ver\s+(.+?)\s*-\s*MonosChinos$",
    re.IGNORECASE,
)


def normalize_monoschinos(filename_stem: str) -> str:
    # Limpiar sufijos _1, _2 que agregan los navegadores en descargas duplicadas
    stem = re.sub(r"_\d+$", "", filename_stem)

    m = MONOSCHINOS_EPISODE_RE.match(stem)
    if m:
        ep_num = m.group(1)
        title = m.group(2).strip()
        return f"{title} - Episodio {ep_num}"

    m = MONOSCHINOS_MOVIE_RE.match(stem)
    if m:
        inner = m.group(1).strip()
        if not re.search(r"\b(movie|pelicula|film)\b", inner, re.IGNORECASE):
            inner = inner + " Movie"
        return inner

    return stem


def parse_episode_info(filename_stem: str):
    stem = normalize_monoschinos(filename_stem)
    m = re.search(r"\bepisodio\s*(\d+)\b", stem, flags=re.IGNORECASE)
    if not m:
        return None, None

    episode = int(m.group(1))
    title_part = stem[: m.start()].strip(" .-_")
    return title_part, episode


def parse_movie_title(filename_stem: str):
    stem = normalize_monoschinos(filename_stem)
    norm = normalize_for_match(stem)
    if not re.search(r"\b(movie|pelicula|film)\b", norm):
        return None

    base = re.split(
        r"\b(movie|pelicula|película|film)\b",
        stem,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    base = base.strip(" .-_")
    return base or filename_stem


def extract_season(title_part: str):
    raw = title_part
    norm = normalize_for_match(raw)

    final_match = re.search(r"\bfinal season\b", norm)
    if final_match:
        raw_clean = re.sub(r"\b[Ff]inal\s+[Ss]eason\b", "", raw).strip(" .-_")
        return raw_clean or raw, "Temporada Final"

    patterns = [
        (r"\b(\d+)(?:st|nd|rd|th)?\s*season\b", r"\b\d+(?:st|nd|rd|th)?\s*[Ss]eason\b"),
        (r"\bseason\s*(\d+)\b", r"\b[Ss]eason\s*\d+\b"),
        (r"\btemporada\s*(\d+)\b", r"\b[Tt]emporada\s*\d+\b"),
        (r"\b(\d+)(?:ra|da)?\s*temporada\b", r"\b\d+(?:ra|da)?\s*[Tt]emporada\b"),
    ]

    for norm_pat, raw_pat in patterns:
        m = re.search(norm_pat, norm)
        if m:
            n = int(m.group(1))
            raw_clean = re.sub(raw_pat, "", raw).strip(" .-_")
            return (raw_clean or raw), f"Temporada {n}"

    # Caso "Titulo 2 Episodio 1" => temporada 2 (sin ser demasiado agresivo)
    m_end_number = re.search(r"^(.*?)(?:\s+)(\d+)$", raw.strip())
    if m_end_number:
        maybe_title = m_end_number.group(1).strip()
        maybe_num = int(m_end_number.group(2))
        if 2 <= maybe_num <= 20 and not re.search(r"\(\d{4}\)$", maybe_title):
            return maybe_title, f"Temporada {maybe_num}"

    return raw, "Temporada 1"


def find_existing_series_folder(root: Path, computed_name: str) -> str:
    """Busca en root una carpeta existente cuyo nombre normalizado coincida
    con computed_name normalizado. Si existe, devuelve su nombre real; si no,
    devuelve computed_name."""
    norm_computed = normalize_for_match(computed_name)
    try:
        for child in root.iterdir():
            if child.is_dir() and normalize_for_match(child.name) == norm_computed:
                return child.name
    except (OSError, PermissionError):
        pass
    return computed_name


def compute_target(path: Path, root: Path):
    title_part, episode = parse_episode_info(path.stem)
    if title_part is not None:
        base_title, season_folder = extract_season(title_part)
        base_title = safe_name(base_title)
        season_folder = safe_name(season_folder)

        # Reutilizar carpeta serie existente si hay coincidencia normalizada
        base_title = find_existing_series_folder(root, base_title)

        target_dir = root / base_title / season_folder
        return target_dir / path.name

    movie_title = parse_movie_title(path.stem)
    if movie_title is not None:
        movie_title = safe_name(movie_title)
        movie_title = find_existing_series_folder(root, movie_title)
        return root / movie_title / "Movies" / path.name

    return None


def build_unique_target(target: Path):
    if not target.exists():
        return target

    for i in range(2, 1000):
        candidate = target.with_name(f"{target.stem}_{i}{target.suffix}")
        if not candidate.exists():
            return candidate
    return target


def iter_video_files(root: Path):
    for p in root.iterdir():
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            yield p


def is_forbidden_source_root(path: Path) -> bool:
    resolved = path.resolve()
    anchor = Path(resolved.anchor)
    return resolved == anchor


def confirm_root_execution(root: Path) -> bool:
    print("\n[WARNING] Has seleccionado la raiz de un disco.")
    print(f"Ruta: {root}")
    print("Esto puede mover muchos archivos por error.")
    print("Escribe exactamente: EJECUTAR EN RAIZ")
    typed = input("> ").strip()
    return typed == "EJECUTAR EN RAIZ"


def should_use_double_click_mode() -> bool:
    return os.name == "nt" and len(sys.argv) == 1


def read_key():
    if os.name == "nt":
        import msvcrt

        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            if ch2 == "H":
                return "UP"
            if ch2 == "P":
                return "DOWN"
            if ch2 == "K":
                return "LEFT"
            if ch2 == "M":
                return "RIGHT"
            return "OTHER"
        if ch in ("\r", "\n"):
            return "ENTER"
        if ch == "\x1b":
            return "ESC"
        return ch

    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            seq = sys.stdin.read(2)
            if seq == "[A":
                return "UP"
            if seq == "[B":
                return "DOWN"
            if seq == "[C":
                return "RIGHT"
            if seq == "[D":
                return "LEFT"
            return "ESC"
        if ch in ("\r", "\n"):
            return "ENTER"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def choose_source_interactive(start_dir: Path):
    current = start_dir.resolve()
    cursor = 0
    scroll = 0

    while True:
        dirs = []
        try:
            dirs = sorted(
                [p for p in current.iterdir() if p.is_dir()],
                key=lambda p: p.name.lower(),
            )
        except PermissionError:
            pass

        if cursor >= len(dirs):
            cursor = max(0, len(dirs) - 1)
        if scroll > cursor:
            scroll = cursor

        term_height = shutil.get_terminal_size((100, 30)).lines
        visible_rows = max(6, term_height - 10)
        if cursor >= scroll + visible_rows:
            scroll = cursor - visible_rows + 1

        clear_screen()
        print("=== Selector de carpeta (estilo navegador) ===")
        print(f"Actual: {current}")
        print("Flechas: ↑/↓ mover  ← subir nivel  → entrar")
        print("Enter: seleccionar carpeta actual | q/Esc: cancelar")
        print("-" * 72)

        if not dirs:
            print("(Sin subcarpetas)")
        else:
            end = min(len(dirs), scroll + visible_rows)
            for idx in range(scroll, end):
                marker = ">" if idx == cursor else " "
                print(f"{marker} {dirs[idx].name}")
            if end < len(dirs):
                print(f"... ({len(dirs) - end} mas)")

        key = read_key()

        if key == "UP":
            if dirs:
                cursor = max(0, cursor - 1)
            continue
        if key == "DOWN":
            if dirs:
                cursor = min(len(dirs) - 1, cursor + 1)
            continue
        if key == "LEFT":
            parent = current.parent
            if parent != current:
                current = parent
                cursor = 0
                scroll = 0
            continue
        if key == "RIGHT":
            if dirs:
                current = dirs[cursor]
                cursor = 0
                scroll = 0
            continue
        if key == "ENTER":
            return current
        if key in ("q", "Q", "ESC"):
            return None


def main():
    parser = argparse.ArgumentParser(
        description="Organiza videos de anime en carpetas Serie/Temporada."
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Carpeta origen (default: carpeta actual).",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Abre selector interactivo de carpetas en consola.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Mueve archivos de verdad (sin esto solo simula).",
    )
    double_click_mode = should_use_double_click_mode()
    if double_click_mode:
        args = parser.parse_args(["--interactive", "--apply"])
    else:
        args = parser.parse_args()

    source_value = args.source
    if source_value is None and (args.interactive or double_click_mode):
        start_dir = Path(__file__).resolve().parent if double_click_mode else Path.cwd()
        selected = choose_source_interactive(start_dir)
        if selected is None:
            print("Operacion cancelada por usuario.")
            return
        source_value = str(selected)

    if source_value is None:
        source_value = "."

    root = Path(source_value).resolve()
    if not root.exists() or not root.is_dir():
        print(f"Carpeta invalida: {root}")
        sys.exit(1)
    if is_forbidden_source_root(root):
        if not confirm_root_execution(root):
            print("Operacion cancelada: no se confirmo ejecucion en raiz.")
            sys.exit(1)

    dry_run = not args.apply
    mode = "SIMULACION" if dry_run else "EJECUCION"
    print(f"[{mode}] Carpeta: {root}")

    total = 0
    moved = 0
    skipped = 0

    for video in iter_video_files(root):
        total += 1
        target = compute_target(video, root)
        if target is None:
            print(f"[SKIP] Sin 'Episodio': {video.name}")
            skipped += 1
            continue

        if target.resolve() == video.resolve():
            print(f"[SKIP] Ya en destino: {video.name}")
            skipped += 1
            continue

        final_target = build_unique_target(target)
        if final_target != target:
            print(
                f"[INFO] Destino duplicado, usando nuevo nombre: {final_target.relative_to(root)}"
            )

        print(f"[MOVE] {video.name} -> {final_target.relative_to(root)}")
        if not dry_run:
            final_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(video), str(final_target))
        moved += 1

    print(f"\nTotal videos: {total} | Movidos: {moved} | Omitidos: {skipped}")
    if dry_run:
        print("Ejecuta con --apply para aplicar cambios.")
    if double_click_mode:
        input("\nProceso terminado. Pulsa Enter para cerrar...")


if __name__ == "__main__":
    main()
