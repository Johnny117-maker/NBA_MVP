"""Entrada do executável Windows; o usuário final não precisa de Python instalado."""

import multiprocessing

from src.desktop_runtime import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
