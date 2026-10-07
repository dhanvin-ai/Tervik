"""Phase 6 discovery: embeddings, cosine-drift segmentation, BIRCH
compression, HDBSCAN-like density grouping, and intent matching.

Local and deterministic: TF-IDF + SVD embeddings (no external service),
scikit-learn BIRCH/HDBSCAN, cosine matching for new traffic. Thresholds
and construction choices are evaluated in scripts/evaluate_discovery.py,
not assumed from the algorithm names.
"""
import hashlib
import re

import numpy as np

DISCOVERY_VERSION = "6.0.0"
MIN_SEGMENT_MESSAGES = 2
SEGMENT_DRIFT_THRESHOLD = 0.25
MATCH_THRESHOLD = 0.35
INTENT_THRESHOLD = 0.30
LABEL_TERMS = 3
# Grouping bars, tuned on scripts/evaluate_discovery.py. Cores merge only on
# mutual-best centroid matches (HDBSCAN's mutual-reachability idea without
# chaining through hubs); leftovers join above ASSIGN_THRESHOLD, and members
# below EJECT_THRESHOLD are ejected so one hub cannot absorb unrelated
# traffic.
MERGE_THRESHOLD = 0.35
ASSIGN_THRESHOLD = 0.30
EJECT_THRESHOLD = 0.30

_WORD = re.compile(r"[a-z0-9]{2,}")
_STOP = frozenset("""
a an and are as at be but by can could did do does for from had has have how i if in is it its
me more most my no not of on or our please should so such that the their there these they this to
us was we what when where which who will with you your yours he she him her his hers its our ours
doe does did done get got getting want need need help hi hello hey thanks thank please just like
""".split())


def _tokenize(text):
    return [w for w in _WORD.findall((text or "").lower()) if w not in _STOP]


def embed_texts(texts):
    """Deterministic L2-normalized embeddings for short conversation texts.

    Evaluated choice (see scripts/evaluate_discovery.py): sparse TF-IDF
    without SVD. Dense SVD projections smeared unrelated short texts
    together (precision collapse); sparse separation keeps mistaken merges
    near zero. A pluggable embedding-model adapter for zero-overlap
    paraphrase recall is the documented next step, not an assumed default.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize
    cleaned = [t if t and t.strip() else "empty" for t in texts]
    vectorizer = TfidfVectorizer(tokenizer=_tokenize, preprocessor=None, lowercase=False,
                                 token_pattern=None,
                                 ngram_range=(1, 2), min_df=1, sublinear_tf=True)
    try:
        matrix = vectorizer.fit_transform(cleaned)
    except ValueError:
        return np.ones((len(cleaned), 1)), vectorizer
    dense = matrix.toarray()
    norms = np.linalg.norm(dense, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return dense / norms, vectorizer


def _cosine(matrix):
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normalized = matrix / norms
    # Rounded so BLAS-level (ARM vs x86) wobble cannot flip thresholds.
    return np.round(normalized @ normalized.T, 6)


def segment_messages(messages):
    """Split a long conversation where meaning drifts (cosine gaps)."""
    texts = [(m.get("content") or "") for m in messages]
    if len(texts) < 6:
        return [list(range(len(texts)))] if texts else []
    matrix, _ = embed_texts(texts)
    similarity = _cosine(matrix)
    cuts, start = [], 0
    for index in range(1, len(texts)):
        if similarity[index - 1, index] < SEGMENT_DRIFT_THRESHOLD:
            cuts.append((start, index))
            start = index
    cuts.append((start, len(texts)))
    merged, pending = [], []
    for start, end in cuts:
        pending.extend(range(start, end))
        if len(pending) >= MIN_SEGMENT_MESSAGES:
            merged.append(pending)
            pending = []
    if pending:
        if merged:
            merged[-1].extend(pending)
        else:
            merged.append(pending)
    return merged


def _birch_centers(matrix, texts=None):
    # Deterministic compression replacing the CF tree. BIRCH was evaluated
    # and removed: its incremental splits flip on ARM-vs-x86 BLAS wobble,
    # which moved the discovery gate across platforms with identical library
    # versions. Exact token-signature compression is platform-proof and
    # keeps the same contract (radius-bounded pure cores): units sharing a
    # normalized token multiset compress to their mean; everything else
    # stays a singleton for mutual-best grouping downstream.
    n = matrix.shape[0]
    if n <= 3:
        return matrix, np.arange(n)
    order = sorted(range(n), key=lambda i: (sorted(texts[i]) if texts else i))
    centers, membership, seen = [], [], {}
    for index in order:
        signature = tuple(sorted(texts[index])) if texts else (index,)
        if signature in seen:
            position = seen[signature]
            members = membership[position]
            combined = np.vstack([matrix[members].mean(axis=0), matrix[index]])
            centers[position] = combined.mean(axis=0)
            membership[position] = np.append(members, index)
        else:
            seen[signature] = len(centers)
            centers.append(matrix[index].copy())
            membership.append(np.asarray([index]))
    return np.asarray(centers), membership


def group_units(matrix, token_sigs=None):
    """Deterministic compression plus mutual-best density grouping.

    Compression groups units sharing a normalized token multiset (exact,
    platform-proof); BIRCH was evaluated and removed after its CF-tree
    splits flipped between ARM and x86 with identical library versions.
    Compressed candidates merge only on mutual-best centroid matches above
    MERGE_THRESHOLD, which keeps dense topics together without chaining
    through shared-word hubs. Leftover units join above ASSIGN_THRESHOLD;
    members below EJECT_THRESHOLD are ejected. Noise is never a group.
    """
    n = matrix.shape[0]
    if n == 0:
        return []
    if n == 1:
        return [-1]
    similarity = _cosine(matrix)
    if n == 2:
        return [0, 0] if float(similarity[0, 1]) >= ASSIGN_THRESHOLD else [-1, -1]
    centers, membership = _birch_centers(matrix, token_sigs)
    order = list(range(len(membership)))
    # Radius-bounded compressed centers with 2+ members are pure cores already.
    groups = []
    assigned = set()
    for members in membership:
        units = sorted(int(m) for m in members)
        if len(units) >= 2:
            groups.append(units)
            assigned.update(units)
    center_matrix = np.asarray(centers, dtype=float)
    norms = np.linalg.norm(center_matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    center_matrix = center_matrix / norms
    center_sim = center_matrix @ center_matrix.T
    best = {}
    for i in order:
        row = [(float(center_sim[i, j]), j) for j in order if j != i]
        row.sort(reverse=True)
        best[i] = row[0] if row else (0.0, -1)
    parent = list(range(len(order)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in order:
        score, j = best[i]
        if j < 0 or score < MERGE_THRESHOLD:
            continue
        _, back = best[j]
        if back == i:  # mutual best: dense with each other, not via a hub
            root_i, root_j = find(i), find(j)
            if root_i != root_j:
                parent[root_i] = root_j
    core_groups = {}
    for center_index in order:
        core_groups.setdefault(find(center_index), []).append(center_index)
    for members in core_groups.values():
        units = sorted(int(u) for center in members for u in membership[center])
        if len(units) >= 2 and not any(u in assigned for u in units):
            groups.append(units)
            assigned.update(units)
    # Strict assignment of leftovers to the nearest core.
    for index in range(n):
        if index in assigned:
            continue
        best_group, best_score = -1, ASSIGN_THRESHOLD
        for group_index, members in enumerate(groups):
            score = float(np.mean([similarity[index, m] for m in members]))
            if score >= best_score:
                best_group, best_score = group_index, score
        if best_group >= 0:
            groups[best_group].append(index)
            assigned.add(index)
    # Eject members that do not belong: peak similarity to mates is weak.
    final = []
    for members in groups:
        if len(members) == 2:
            pair = float(similarity[members[0], members[1]])
            final.append(members if pair >= EJECT_THRESHOLD else [])
            continue
        kept = [m for m in members
                if max(float(similarity[m, o]) for o in members if o != m) >= EJECT_THRESHOLD]
        final.append(kept if len(kept) >= 2 else [])
    unit_labels = [-1] * n
    for group_index, members in enumerate(final):
        for member in members:
            unit_labels[member] = group_index
    return unit_labels


def group_key(member_ids):
    digest = hashlib.sha1(",".join(sorted(member_ids)).encode()).hexdigest()
    return digest[:16]


def label_for(members_text, vectorizer=None):
    from collections import Counter
    counts = Counter()
    for text in members_text:
        counts.update(set(_tokenize(text)))
    top = [word for word, _ in counts.most_common(LABEL_TERMS)]
    return " · ".join(top) if top else "general"


def discover(units):
    """Group conversation units. `units`: [{id, text}]. Returns groups with
    stable keys, labels, medoid representatives, and centroids."""
    texts = [u["text"] for u in units]
    if not units:
        return []
    matrix, _ = embed_texts(texts)
    token_sigs = [tuple(sorted(_tokenize(t))) for t in texts]
    labels = group_units(matrix, token_sigs)
    groups, by_label = [], {}
    for index, label in enumerate(labels):
        if label < 0:
            continue
        by_label.setdefault(int(label), []).append(index)
    similarity = _cosine(matrix)
    for label, members in sorted(by_label.items()):
        if len(members) < 2:
            continue
        member_ids = [units[i]["id"] for i in members]
        scores = similarity[np.ix_(members, members)].mean(axis=1)
        medoid = members[int(np.argmax(scores))]
        centroid = matrix[members].mean(axis=0)
        norm = float(np.linalg.norm(centroid)) or 1.0
        groups.append({
            "key": group_key(member_ids),
            "member_ids": member_ids,
            "label": label_for([texts[i] for i in members]),
            "representative_id": units[medoid]["id"],
            "representative_text": texts[medoid][:280],
            "count": len(members),
            "centroid": (centroid / norm).tolist(),
        })
    return sorted(groups, key=lambda g: (-g["count"], g["key"]))


def match_centroid(centroid, groups):
    """Assign new traffic to an existing group or None."""
    vector = np.asarray(centroid, dtype=float)
    best, best_score = None, MATCH_THRESHOLD
    for group in groups:
        center = np.asarray(group["centroid"], dtype=float)
        score = float(vector @ center)
        if score >= best_score:
            best, best_score = group, score
    return best


def match_intent(text, intents):
    """Match one conversation against configured intent examples."""
    active = [intent for intent in intents if intent.get("enabled", True) and intent.get("examples")]
    if not active or not (text or "").strip():
        return None
    corpus = [text] + [example for intent in active for example in intent["examples"][:8]]
    matrix, _ = embed_texts(corpus)
    first = matrix[0]
    offset, best, best_score = 1, None, INTENT_THRESHOLD
    for intent in active:
        examples = intent["examples"][:8]
        scores = [float(first @ matrix[offset + i]) for i in range(len(examples))]
        offset += len(examples)
        top = max(scores) if scores else 0.0
        if top >= best_score:
            best, best_score = intent, top
    if best is None:
        return None
    return {"intent_id": best["id"], "intent_name": best["name"], "score": round(best_score, 3)}
