"""Arranque rápido del servidor: python run.py"""

import uvicorn

if __name__ == "__main__":
    # --reload recarga la app al editar el código fuente
    uvicorn.run("src.main:app", host="127.0.0.1", port=8000, reload=True)