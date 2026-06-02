"""Shim package so `from solvers.X import …` in app.py resolves to the solver
modules that live at the repo root (procurement.py, calendar.py, profitmix.py, …).

The solver files were never moved under a real package; app.py imports them as
`solvers.*`. Rather than relocate ~20 modules (and rewrite their cross-imports),
we extend THIS package's search path to include the repo root, so
`import solvers.procurement` loads <repo-root>/procurement.py. Intra-solver
imports by bare name (e.g. `import forecast`) keep working via sys.path because
app.py runs from the repo root.
"""
import os as _os

_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in __path__:
    __path__.append(_ROOT)
