import os, pickle, numpy as np, faiss
from pdf_utils import read_pdf
from llama_api import embed_text
EMBEDDING_DB = 'results/embeddings.index'
META_DB = 'results/metadata.pkl'
os.makedirs('results', exist_ok=True)

def build_index_from_resumes(resume_dir='candidates'):
    metas = []
    vecs = []
    for fname in sorted(os.listdir(resume_dir)):
        if fname.lower().endswith('.pdf'):
            path = os.path.join(resume_dir, fname)
            text = read_pdf(path)
            emb = embed_text(text)
            if emb is None:
                print(f"[ERROR] Could not get embedding for {fname}. Skipping.")
                continue
            emb = np.array(emb, dtype='float32')
            metas.append({'file': path})
            vecs.append(emb)
    if not vecs:
        raise RuntimeError('No valid embeddings found. Check embedding service.')
    X = np.vstack(vecs)
    dim = X.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(X)
    faiss.write_index(index, EMBEDDING_DB)
    with open(META_DB, 'wb') as f:
        pickle.dump(metas, f)
    return len(metas)

def search_jd(jd_path, top_k=5):
    if not os.path.exists(EMBEDDING_DB) or not os.path.exists(META_DB):
        raise RuntimeError('Index not built')
    jd_text = read_pdf(jd_path)
    emb = embed_text(jd_text)
    if emb is None:
        raise RuntimeError('Failed to get embedding for JD. Embedding service may be down.')
    q = np.array(emb, dtype='float32').reshape(1,-1)
    index = faiss.read_index(EMBEDDING_DB)
    with open(META_DB,'rb') as f:
        metas = pickle.load(f)
    D,I = index.search(q, top_k)
    results = [metas[i] for i in I[0]]
    return results
