"""
Sequence-dependent changeover sequencing (GAP-8, move a)
========================================================
production.py keeps the MILP linear by charging changeover as a switch COUNT times
the MEAN of the changeover matrix (production.py ~222: "expected-value average over
eligible pairs"). That throws away the asymmetric, sequence-dependent structure of
real setups (A→B ≠ B→A; some run orders are far cheaper).

This module computes the true minimum sequence-dependent changeover for the set of
SKUs actually scheduled on a line: a shortest Hamiltonian PATH over the asymmetric
changeover matrix (production runs the SKUs in an order, so it's an open ATSP, not a
cycle). Exact by held-karp/permutation for small lines (the common case — a handful
of SKUs), nearest-neighbour + node-reinsertion local search above that. It runs
post-solve, so it sharpens the reported changeover cost and hands planners the run
order without destabilising the MILP.
"""
import itertools


def _matrix_lookup(matrix, a, b):
    """Changeover minutes from SKU a → b. Supports nested {a:{b:m}} and flat {'a->b':m}."""
    if not matrix:
        return None
    if a in matrix and isinstance(matrix[a], dict) and b in matrix[a]:
        return float(matrix[a][b])
    for key in (f'{a}->{b}', f'{a}|{b}', f'{a},{b}'):
        if key in matrix:
            return float(matrix[key])
    return None


def _path_cost(seq, cost_fn):
    return sum(cost_fn(seq[i], seq[i + 1]) for i in range(len(seq) - 1))


def optimal_sequence(skus, matrix, default_min=30.0):
    """Shortest open-path run order over the asymmetric changeover matrix.

    skus    : list of SKU identifiers scheduled on the line
    matrix  : asymmetric changeover (minutes) — nested or flat (see _matrix_lookup)
    Returns {sequence, total_changeover_min, n_changeovers, basis}.
    """
    skus = list(dict.fromkeys(skus))  # dedupe, preserve order
    n = len(skus)
    if n <= 1:
        return {'sequence': skus, 'total_changeover_min': 0.0, 'n_changeovers': 0, 'basis': 'trivial'}

    def cost(a, b):
        v = _matrix_lookup(matrix, a, b)
        return default_min if v is None else v

    if n <= 8:
        # Exact: cheapest Hamiltonian path over all start orders (n! ≤ 40320).
        best, best_cost = None, float('inf')
        for perm in itertools.permutations(skus):
            c = _path_cost(perm, cost)
            if c < best_cost:
                best, best_cost = perm, c
        basis = 'exact'
    else:
        # Heuristic: nearest-neighbour from each start, then node-reinsertion local search.
        best, best_cost = None, float('inf')
        for start in skus:
            unvisited = set(skus); unvisited.discard(start)
            seq = [start]
            while unvisited:
                last = seq[-1]
                nxt = min(unvisited, key=lambda b: cost(last, b))
                seq.append(nxt); unvisited.discard(nxt)
            improved = True
            while improved:
                improved = False
                for i in range(len(seq)):
                    for j in range(len(seq)):
                        if i == j:
                            continue
                        cand = seq[:i] + seq[i + 1:]
                        cand.insert(j, seq[i])
                        if _path_cost(cand, cost) + 1e-9 < _path_cost(seq, cost):
                            seq = cand; improved = True
            c = _path_cost(seq, cost)
            if c < best_cost:
                best, best_cost = list(seq), c
        basis = 'heuristic'

    return {
        'sequence': list(best),
        'total_changeover_min': round(best_cost, 2),
        'n_changeovers': len(best) - 1,
        'basis': basis,
    }


def evaluate_line(data):
    """Endpoint wrapper. data = {skus:[...], changeover_matrix:{...}, default_min?,
    averaged_min?}. Returns the optimal sequence plus the averaged-approximation cost
    for contrast (the saving the sequence-dependent model captures)."""
    skus = data.get('skus', []) or []
    matrix = data.get('changeover_matrix', {}) or {}
    default_min = float(data.get('default_min', 30) or 30)
    res = optimal_sequence(skus, matrix, default_min)
    # Averaged approximation = (n−1) switches × mean of the defined matrix entries.
    vals = []
    for a in skus:
        for b in skus:
            if a == b:
                continue
            v = _matrix_lookup(matrix, a, b)
            if v is not None:
                vals.append(v)
    mean_min = (sum(vals) / len(vals)) if vals else default_min
    averaged = round(mean_min * max(0, len(set(skus)) - 1), 2)
    res['averaged_approx_min'] = averaged
    res['sequence_saving_min'] = round(averaged - res['total_changeover_min'], 2)
    res['mean_changeover_min'] = round(mean_min, 2)
    return res
