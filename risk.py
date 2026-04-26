"""
Risk — HMM Regime Detection (Round 4 P6 deferred completion)
=============================================================
Two-state Gaussian Hidden Markov Model for classifying a 1D price/cost time
series into LOW-VOL vs HIGH-VOL regimes.

Algorithm:
  1. K-means seed on the absolute first-difference series to get initial
     low-vol vs high-vol means/variances.
  2. Baum-Welch (EM) iterations refine emission means, emission variances,
     transition matrix, and start probabilities.
  3. Viterbi decodes the most-likely state sequence.
  4. Output is the per-period regime label + the persistence (diagonal of A)
     + the implied variance ratio (sigma_high / sigma_low).

Intentionally self-contained — only depends on `numpy` (already in
requirements.txt for montecarlo). No scipy / hmmlearn.

API:
  detect_regimes(series, n_iter=30, k_states=2) -> {
      'states':[0,0,1,1,0,...],   # one label per period
      'state_labels':['low-vol','high-vol'],
      'mu':[μ_low, μ_high],
      'sigma':[σ_low, σ_high],
      'transmat':[[a00,a01],[a10,a11]],
      'persistence':[a00,a11],
      'sigma_ratio': σ_high / σ_low,
      'n_periods': len(series),
      'current_regime':'low-vol'|'high-vol',
      'n_high_periods': count of t labelled high-vol,
      'log_likelihood': log P(series|model),
  }
"""
import math
import numpy as np


def _gauss_logpdf(x, mu, var):
    """Log Gaussian PDF (vectorised)."""
    var = max(float(var), 1e-9)
    return -0.5 * (math.log(2 * math.pi * var) + ((x - mu) ** 2) / var)


def _kmeans_seed(diffs, k=2, n_iter=20):
    """Tiny 1-D k-means to seed HMM emission parameters from |Δprice|."""
    if len(diffs) < k:
        return np.array([np.mean(diffs)] * k), np.array([np.var(diffs) + 1e-6] * k)
    lo = float(np.min(diffs))
    hi = float(np.max(diffs))
    centers = np.linspace(lo, hi, k)
    for _ in range(n_iter):
        # Assign
        d2 = np.abs(diffs[:, None] - centers[None, :])
        labels = np.argmin(d2, axis=1)
        # Update
        new_centers = np.array([
            float(np.mean(diffs[labels == j])) if np.any(labels == j) else centers[j]
            for j in range(k)
        ])
        if np.allclose(new_centers, centers):
            break
        centers = new_centers
    # Per-cluster variance
    variances = np.array([
        float(np.var(diffs[labels == j])) if np.any(labels == j) else float(np.var(diffs)) + 1e-6
        for j in range(k)
    ])
    # Sort so cluster 0 = low-vol, cluster 1 = high-vol
    order = np.argsort(centers)
    return centers[order], variances[order]


def _baum_welch(obs, mu, sigma2, A, pi, n_iter=30, tol=1e-4):
    """Forward-backward EM for a 2-state Gaussian HMM. obs is 1-D numpy array."""
    T = len(obs)
    K = len(mu)
    log_lik_prev = -np.inf
    final_ll = log_lik_prev
    for it in range(n_iter):
        # ─── E-step: forward (alpha) and backward (beta) in log-space ───
        log_emit = np.zeros((T, K))
        for j in range(K):
            log_emit[:, j] = _gauss_logpdf(obs, mu[j], sigma2[j])
        log_A = np.log(np.maximum(A, 1e-12))
        log_pi = np.log(np.maximum(pi, 1e-12))

        log_alpha = np.full((T, K), -np.inf)
        log_alpha[0] = log_pi + log_emit[0]
        for t in range(1, T):
            for j in range(K):
                # log-sum-exp over previous states
                v = log_alpha[t - 1] + log_A[:, j]
                m = np.max(v)
                log_alpha[t, j] = m + math.log(np.sum(np.exp(v - m))) + log_emit[t, j]

        log_beta = np.full((T, K), -np.inf)
        log_beta[T - 1] = 0.0
        for t in range(T - 2, -1, -1):
            for i in range(K):
                v = log_A[i, :] + log_emit[t + 1] + log_beta[t + 1]
                m = np.max(v)
                log_beta[t, i] = m + math.log(np.sum(np.exp(v - m)))

        # log-likelihood
        m = np.max(log_alpha[T - 1])
        log_lik = m + math.log(np.sum(np.exp(log_alpha[T - 1] - m)))
        if abs(log_lik - log_lik_prev) < tol:
            final_ll = log_lik
            break
        log_lik_prev = log_lik
        final_ll = log_lik

        # γ_t(i) = P(state=i | obs)
        log_gamma = log_alpha + log_beta - log_lik
        gamma = np.exp(log_gamma)

        # ξ_t(i,j) = P(state_t=i, state_{t+1}=j | obs)
        log_xi = np.full((T - 1, K, K), -np.inf)
        for t in range(T - 1):
            for i in range(K):
                for j in range(K):
                    log_xi[t, i, j] = (log_alpha[t, i] + log_A[i, j]
                                       + log_emit[t + 1, j] + log_beta[t + 1, j] - log_lik)
        xi = np.exp(log_xi)

        # ─── M-step ───
        pi = gamma[0] / np.sum(gamma[0])
        denom = np.sum(gamma[:-1], axis=0)
        for i in range(K):
            for j in range(K):
                A[i, j] = np.sum(xi[:, i, j]) / max(denom[i], 1e-9)
            A[i] /= np.sum(A[i])
        for j in range(K):
            wsum = np.sum(gamma[:, j])
            if wsum > 1e-9:
                mu[j] = np.sum(gamma[:, j] * obs) / wsum
                sigma2[j] = np.sum(gamma[:, j] * (obs - mu[j]) ** 2) / wsum + 1e-6
    return mu, sigma2, A, pi, final_ll


def _viterbi(obs, mu, sigma2, A, pi):
    """Decode the most-likely state path (log-space)."""
    T = len(obs)
    K = len(mu)
    log_A = np.log(np.maximum(A, 1e-12))
    log_pi = np.log(np.maximum(pi, 1e-12))
    log_emit = np.zeros((T, K))
    for j in range(K):
        log_emit[:, j] = _gauss_logpdf(obs, mu[j], sigma2[j])

    delta = np.full((T, K), -np.inf)
    psi = np.zeros((T, K), dtype=int)
    delta[0] = log_pi + log_emit[0]
    for t in range(1, T):
        for j in range(K):
            scores = delta[t - 1] + log_A[:, j]
            psi[t, j] = int(np.argmax(scores))
            delta[t, j] = float(np.max(scores)) + log_emit[t, j]
    states = np.zeros(T, dtype=int)
    states[T - 1] = int(np.argmax(delta[T - 1]))
    for t in range(T - 2, -1, -1):
        states[t] = psi[t + 1, states[t + 1]]
    return states


def detect_regimes(series, n_iter=30, k_states=2):
    """Public entry. `series` is a 1-D list/array of prices (or any 1-D series).

    Returns: dict described in the module docstring. If <8 points → falls back
    to a simple stddev classification (no HMM)."""
    s = np.array([float(x) for x in series if x is not None], dtype=float)
    if len(s) < 8:
        # Fallback: split by global stddev. Not really HMM, but useful UI.
        if len(s) < 2:
            return {'error': 'series too short', 'n_periods': len(s)}
        diffs = np.abs(np.diff(s))
        thr = float(np.median(diffs))
        states = (diffs > thr).astype(int).tolist()
        # Pad first state to match length
        states = [states[0]] + states
        return {
            'states': states,
            'state_labels': ['low-vol', 'high-vol'],
            'mu': [float(np.mean(s[:len(s)//2])), float(np.mean(s[len(s)//2:]))],
            'sigma': [float(np.std(s) * 0.5), float(np.std(s) * 1.5)],
            'transmat': [[0.8, 0.2], [0.2, 0.8]],
            'persistence': [0.8, 0.8],
            'sigma_ratio': 3.0,
            'n_periods': len(s),
            'current_regime': 'high-vol' if states[-1] == 1 else 'low-vol',
            'n_high_periods': int(sum(states)),
            'log_likelihood': None,
            'fallback': 'stddev-threshold (series too short for HMM EM)',
        }

    # Use first-difference as the observation — captures volatility regime shifts.
    obs = np.diff(s)
    if np.std(obs) < 1e-9:
        # constant series
        return {
            'states': [0] * len(s),
            'state_labels': ['low-vol', 'high-vol'],
            'mu': [float(np.mean(s)), float(np.mean(s))],
            'sigma': [0.0, 0.0],
            'transmat': [[1, 0], [0, 1]],
            'persistence': [1, 1],
            'sigma_ratio': 1.0,
            'n_periods': len(s),
            'current_regime': 'low-vol',
            'n_high_periods': 0,
            'log_likelihood': None,
            'fallback': 'flat series',
        }

    abs_obs = np.abs(obs)
    seed_mu, seed_var = _kmeans_seed(abs_obs, k=k_states)
    # Map back to signed obs domain — initial μ for both states = 0 (drift), σ from cluster spread.
    mu = np.array([0.0, 0.0])
    sigma2 = np.array([max(float(seed_var[0]), 1e-3), max(float(seed_var[1]), 1e-3)])
    if sigma2[1] < sigma2[0]:
        sigma2 = sigma2[::-1]
    # Persistent transition matrix (stay-in-state ~0.85)
    A = np.array([[0.85, 0.15], [0.15, 0.85]])
    pi = np.array([0.5, 0.5])

    mu, sigma2, A, pi, ll = _baum_welch(obs, mu, sigma2, A, pi, n_iter=n_iter)

    # Re-sort so state 0 = lower variance = low-vol
    if sigma2[0] > sigma2[1]:
        mu = mu[::-1]
        sigma2 = sigma2[::-1]
        A = A[::-1, ::-1]
        pi = pi[::-1]

    states = _viterbi(obs, mu, sigma2, A, pi).tolist()
    # Pad first observation to match input length (first obs is diff[0] = s[1]-s[0])
    states = [states[0]] + states

    sigma = np.sqrt(np.maximum(sigma2, 1e-12))
    return {
        'states': [int(x) for x in states],
        'state_labels': ['low-vol', 'high-vol'],
        'mu': [round(float(mu[0]), 4), round(float(mu[1]), 4)],
        'sigma': [round(float(sigma[0]), 4), round(float(sigma[1]), 4)],
        'transmat': [[round(float(A[i, j]), 4) for j in range(2)] for i in range(2)],
        'persistence': [round(float(A[0, 0]), 4), round(float(A[1, 1]), 4)],
        'sigma_ratio': round(float(sigma[1] / max(sigma[0], 1e-9)), 3),
        'n_periods': len(s),
        'current_regime': 'high-vol' if states[-1] == 1 else 'low-vol',
        'n_high_periods': int(sum(1 for x in states if x == 1)),
        'log_likelihood': round(float(ll), 4),
    }


def detect_many(payload):
    """Batch entry. payload = {'rows':[{'name','series'},...], 'n_iter':30}.
    Returns: {'rows':[{'name','result'},...], 'meta':{...}}."""
    rows = payload.get('rows', [])
    n_iter = int(payload.get('n_iter', 30))
    out = []
    for r in rows:
        try:
            series = r.get('series', [])
            res = detect_regimes(series, n_iter=n_iter)
            out.append({'name': r.get('name', ''), 'result': res})
        except Exception as e:
            out.append({'name': r.get('name', ''), 'result': {'error': str(e)}})
    return {'rows': out, 'meta': {'n_iter': n_iter, 'rows_processed': len(out)}}
