"""SCP — supply chain planning engine."""
import os

# numpy's maths library (OpenBLAS) starts a thread per core in every process. The engine's matrices are small, so
# those threads buy nothing, and the forecast's pool of worker processes, each with that many threads, spent its time
# fighting over the cores: 300 series took 113 s instead of 6 s. Read once, when numpy loads, so it is set here,
# before anything imports numpy; a value set in the environment wins.
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

__version__ = "0.1.0"
