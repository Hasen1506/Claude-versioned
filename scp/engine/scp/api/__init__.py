"""FastAPI application: `uvicorn scp.api.app:app`."""
import os

# One math-library thread per request. The engine's arrays are small, so extra BLAS threads only spin: on a host
# limited to a fraction of a CPU they burn the quota for nothing (a proof run used ~1.8× the CPU and ran many times
# slower). Set before numpy loads; an explicit environment setting still wins.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")
