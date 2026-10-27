"""Traceable chunking, SQLite vector storage and retrieval."""
import json
import math
import re
from datetime import datetime, timezone

from .ai_clients import AIClientError

MAX_CHARS = 800
OVERLAP = 80
VECTOR_THRESHOLD = 0.35
RRF_K = 60


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def split_text(text, max_chars=MAX_CHARS, overlap=OVERLAP):
    text = text or ''
    if len(text) <= max_chars:
        return [(0, len(text), text)] if text else []
    chunks = []
    start = 0
    while start < len(text):
        hard_end = min(len(text), start + max_chars)
        end = hard_end
        if hard_end < len(text):
            window = text[start:hard_end]
            candidates = [window.rfind('\n\n'), window.rfind('\n'), window.rfind('。'), window.rfind('.')]
            cut = max(candidates)
            if cut >= max_chars * 0.55:
                end = start + cut + 1
        chunk = text[start:end].strip()
        if chunk:
            real_start = start + (len(text[start:end]) - len(text[start:end].lstrip()))
            real_end = end - (len(text[start:end]) - len(text[start:end].rstrip()))
            chunks.append((real_start, real_end, text[real_start:real_end]))
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def cosine_similarity(left, right):
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    ln = math.sqrt(sum(a * a for a in left))
    rn = math.sqrt(sum(b * b for b in right))
    return dot / (ln * rn) if ln and rn else 0.0


def rebuild_material_index(conn, material_id, class_id, embedding_client):
    row = conn.execute(
        'SELECT id,body_text FROM knowledge_entries WHERE material_id=? AND class_id=?',
        (material_id, class_id),
    ).fetchone()
    if row is None:
        return {'chunks': 0, 'failed': 0}
    with conn:
        conn.execute('DELETE FROM knowledge_chunks WHERE material_id=? AND class_id=?', (material_id, class_id))
        chunks = split_text(row['body_text'])
        failed = 0
        for idx, (start, end, chunk_text) in enumerate(chunks):
            chunk_id = conn.execute(
                '''INSERT INTO knowledge_chunks(
                   knowledge_entry_id,material_id,class_id,chunk_index,chunk_text,start_offset,end_offset,index_status,updated_at
                   ) VALUES (?,?,?,?,?,?,?,'pending',?)''',
                (row['id'], material_id, class_id, idx, chunk_text, start, end, utc_now()),
            ).lastrowid
            try:
                vector = embedding_client.embed(chunk_text)
                conn.execute(
                    '''INSERT OR REPLACE INTO knowledge_chunk_embeddings(
                       chunk_id,class_id,embedding,embedding_model,embedding_dim
                       ) VALUES (?,?,?,?,?)''',
                    (chunk_id, class_id, json.dumps(vector), embedding_client.model, embedding_client.dim),
                )
                conn.execute(
                    "UPDATE knowledge_chunks SET index_status='ready',index_error=NULL,updated_at=? WHERE id=? AND class_id=?",
                    (utc_now(), chunk_id, class_id),
                )
            except Exception as exc:
                failed += 1
                conn.execute(
                    "UPDATE knowledge_chunks SET index_status='failed',index_error=?,updated_at=? WHERE id=? AND class_id=?",
                    (safe_error(exc), utc_now(), chunk_id, class_id),
                )
    return {'chunks': len(chunks), 'failed': failed}


def safe_error(exc):
    text = str(exc)
    text = re.sub(r'Bearer\s+[A-Za-z0-9._\-]+', 'Bearer <redacted>', text)
    return text[:300]


class SQLiteVectorStore:
    def __init__(self, conn):
        self.conn = conn

    def ready_vectors(self, class_id, dim):
        rows = self.conn.execute(
            '''SELECT c.id,c.class_id,e.embedding
               FROM knowledge_chunks c JOIN knowledge_chunk_embeddings e ON e.chunk_id=c.id AND e.class_id=c.class_id
               WHERE c.class_id=? AND c.index_status='ready' AND e.embedding_dim=?''',
            (class_id, dim),
        ).fetchall()
        for row in rows:
            yield row['id'], json.loads(row['embedding'])

    def search(self, class_id, query_vector, dim, limit=8, threshold=VECTOR_THRESHOLD):
        scored = []
        for chunk_id, vector in self.ready_vectors(class_id, dim):
            score = cosine_similarity(query_vector, vector)
            if score >= threshold:
                scored.append((chunk_id, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]


def keyword_search(conn, class_id, query, limit=8):
    raw_terms = [part for part in re.split(r'\s+', query.strip()) if part]
    terms = []
    for term in raw_terms:
        lowered = term.lower()
        terms.append(lowered)
        cjk = ''.join(re.findall(r'[\u4e00-\u9fff]', lowered))
        if len(cjk) > 2:
            terms.extend(cjk[i:i + 2] for i in range(len(cjk) - 1))
    terms = list(dict.fromkeys(terms))
    if not terms:
        return []
    rows = conn.execute(
        '''SELECT c.*,m.title AS material_title
           FROM knowledge_chunks c JOIN materials m ON m.id=c.material_id AND m.class_id=c.class_id
           WHERE c.class_id=? AND c.index_status='ready'
           ORDER BY c.material_id,c.chunk_index''',
        (class_id,),
    ).fetchall()
    scored = []
    for row in rows:
        text = row['chunk_text'].lower()
        title = row['material_title'].lower()
        score = sum(text.count(term) * 2 + title.count(term) for term in terms)
        if score:
            scored.append((row['id'], float(score)))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]


def hydrate_results(conn, class_id, scored):
    if not scored:
        return []
    ids = [chunk_id for chunk_id, _ in scored]
    placeholders = ','.join('?' for _ in ids)
    rows = conn.execute(
        f'''SELECT c.id AS chunk_id,c.material_id,m.title AS material_title,c.chunk_index,
                   c.start_offset,c.end_offset,c.chunk_text
            FROM knowledge_chunks c JOIN materials m ON m.id=c.material_id AND m.class_id=c.class_id
            WHERE c.class_id=? AND c.id IN ({placeholders})''',
        [class_id, *ids],
    ).fetchall()
    by_id = {row['chunk_id']: row for row in rows}
    results = []
    for rank, (chunk_id, score) in enumerate(scored, start=1):
        row = by_id.get(chunk_id)
        if row is None:
            continue
        text = row['chunk_text']
        excerpt = text if len(text) <= 300 else text[:297] + '...'
        results.append({
            'material_id': row['material_id'],
            'material_title': row['material_title'],
            'chunk_id': row['chunk_id'],
            'chunk_index': row['chunk_index'],
            'start_offset': row['start_offset'],
            'end_offset': row['end_offset'],
            'excerpt': excerpt,
            'score': score,
            'rank': rank,
            'source_url': f'/materials/{row["material_id"]}',
        })
    return results


def rrf_fuse(keyword_hits, vector_hits, limit=8):
    scores = {}
    for hits in (keyword_hits, vector_hits):
        for rank, (chunk_id, _score) in enumerate(hits, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]


def search_knowledge(conn, class_id, query, mode, embedding_client=None, limit=8):
    mode = mode if mode in ('keyword', 'vector', 'hybrid') else 'hybrid'
    query = (query or '').strip()
    if not query:
        raise ValueError('问题不能为空')
    if mode == 'keyword':
        return hydrate_results(conn, class_id, keyword_search(conn, class_id, query, limit)), {'mode': 'keyword'}
    if mode == 'vector':
        if embedding_client is None:
            raise AIClientError('embedding 客户端未配置')
        try:
            qv = embedding_client.embed(query)
        except Exception as exc:
            raise AIClientError(safe_error(exc)) from exc
        vector_hits = SQLiteVectorStore(conn).search(class_id, qv, embedding_client.dim, limit)
        return hydrate_results(conn, class_id, vector_hits), {'mode': 'vector'}
    keyword_hits = keyword_search(conn, class_id, query, limit)
    vector_hits = []
    vector_error = None
    if embedding_client is not None:
        try:
            qv = embedding_client.embed(query)
            vector_hits = SQLiteVectorStore(conn).search(class_id, qv, embedding_client.dim, limit)
        except Exception as exc:
            vector_error = safe_error(exc)
    fused = rrf_fuse(keyword_hits, vector_hits, limit)
    meta = {'mode': 'hybrid', 'degraded': bool(vector_error), 'degrade_reason': vector_error}
    return hydrate_results(conn, class_id, fused), meta
