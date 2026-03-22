import json
import os
import time
from datetime import datetime

import numpy as np
import psycopg2
import torch
from psycopg2.extras import execute_batch
from sentence_transformers import SentenceTransformer

MODEL_NAME = "intfloat/e5-base-v2"
EMBED_DIM = 768
ENCODE_BATCH = 128
INSERT_BATCH = 200
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

DB_NAME = os.getenv("POSTGRES_DB", "interiit_nlp3")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "secretpassword")
DB_HOST = os.getenv("POSTGRES_HOST", "db")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")

DATA_DIR = "/app/data"
TRANSCRIPTS_PATH = os.path.join(DATA_DIR, "transcripts_data.json")
PARTITIONS_PATH = os.path.join(DATA_DIR, "partitioned_data.json")
DISCOVERED_SIGNALS_PATH = os.path.join(DATA_DIR, "signal_data.json")

print(f"Loading model: {MODEL_NAME} on device: {DEVICE}")
model = SentenceTransformer(MODEL_NAME, device=DEVICE)


def embedding_to_pgvector_literal(emb):
    return "[" + ",".join(map(str, map(float, emb))) + "]"


def parse_iso_timestamp(ts):
    if not ts:
        return None
    try:
        if isinstance(ts, str) and ts.endswith("Z"):
            ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def wait_for_db(max_retries=30, delay=2):
    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                host=DB_HOST,
                port=DB_PORT,
            )
            conn.close()
            print("Database is ready!")
            return True
        except psycopg2.OperationalError as e:
            print(
                f"Attempt {attempt + 1}/{max_retries}: Database not ready yet... ({e})")
            time.sleep(delay)
    print("Failed to connect to database after max retries")
    return False


def main():
    if not wait_for_db():
        return

    print(f"Loading transcripts from {TRANSCRIPTS_PATH}")
    with open(TRANSCRIPTS_PATH, "r") as f:
        transcripts = json.load(f)

    print(f"Loading partitions from {PARTITIONS_PATH}")
    with open(PARTITIONS_PATH, "r") as f:
        partitions = json.load(f)

    print(f"Loading discovered signals from {DISCOVERED_SIGNALS_PATH}")
    with open(DISCOVERED_SIGNALS_PATH, "r") as f:
        discovered_signals = json.load(f)

    issue_categories_lookup = {}
    sample_response = discovered_signals.get("sample_response", [])
    for item in sample_response:
        tid = item.get("transcript_id")
        detected_topic = item.get("detected_topic")
        if tid and detected_topic:
            issue_categories_lookup[tid] = detected_topic

    # Build a lookup for transcript metadata (domain, intent)
    transcript_metadata = {}
    for t in transcripts:
        tid = t.get("transcript_id")
        transcript_metadata[tid] = {
            "domain": t.get("domain"),
            "intent": t.get("intent"),
            "issue_categories": issue_categories_lookup.get(tid)
        }

    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
    )
    cur = conn.cursor()

    print(f"Inserting {len(transcripts)} transcripts...")
    upsert_transcript_q = """
    INSERT INTO transcripts (transcript_id, domain, intent, issue_categories, timestamp)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (transcript_id) DO NOTHING
    """

    for i, t in enumerate(transcripts):
        tid = t.get("transcript_id")
        domain = t.get("domain")
        intent = t.get("intent")
        ts_raw = t.get("time_of_interaction") or t.get("timestamp")
        ts = parse_iso_timestamp(ts_raw)
        issue = issue_categories_lookup.get(tid)
        issue_arr = [issue] if issue else None

        cur.execute(upsert_transcript_q, (tid, domain, intent, issue_arr, ts))

        if (i + 1) % 1000 == 0:
            print(f"Inserted {i + 1}/{len(transcripts)} transcripts")

    conn.commit()
    print(f"Inserted all {len(transcripts)} transcripts")

    chunks_to_insert = []
    data_list = partitions.get("data", [])

    # Build full transcript text lookup by combining all chunks per transcript
    transcript_full_text = {}

    print(f"Preparing chunks from {len(data_list)} conversations...")
    for i, conv in enumerate(data_list):
        conv_id = conv.get("id")
        chunks = conv.get("chunks", []) or []
        
        # Combine all chunk texts to form the full transcript
        full_text_parts = []
        
        for j, chunk in enumerate(chunks):
            start_index = chunk.get("start_index")
            end_index = chunk.get("end_index")
            agent_tags = chunk.get("agent_tags") or []
            customer_tags = chunk.get("customer_tags") or []
            outcome_tags = chunk.get("outcome_tags")
            conversation_text = chunk.get("text", "")

            if not isinstance(agent_tags, list):
                agent_tags = [agent_tags] if agent_tags else []
            if not isinstance(customer_tags, list):
                customer_tags = [customer_tags] if customer_tags else []

            all_tags = agent_tags + customer_tags
            if outcome_tags is not None:
                all_tags.extend(outcome_tags if isinstance(
                    outcome_tags, list) else [outcome_tags])

            s_e = f"{start_index}_{end_index}"
            chunks_to_insert.append({
                "start_end": s_e,
                "chunk_id": j,
                "transcript_id": conv_id,
                "text": conversation_text,
                "tags": all_tags
            })
            
            # Add to full text
            full_text_parts.append(conversation_text)

        # Store the full transcript text
        if conv_id and full_text_parts:
            transcript_full_text[conv_id] = " ".join(full_text_parts)

        if (i + 1) % 100 == 0:
            print(
                f"Prepared chunks for {i + 1}/{len(data_list)} conversations")

    print(f"Total chunks to encode: {len(chunks_to_insert)}")

    texts = [c["text"] for c in chunks_to_insert]
    all_embeddings = []
    for i in range(0, len(texts), ENCODE_BATCH):
        batch_texts = texts[i:i + ENCODE_BATCH]
        batch_embs = model.encode(batch_texts, show_progress_bar=True)
        batch_embs = [np.asarray(e).tolist() for e in batch_embs]
        all_embeddings.extend(batch_embs)
        print(
            f"Encoded batch {i // ENCODE_BATCH + 1} / {(len(texts) + ENCODE_BATCH - 1) // ENCODE_BATCH}")

    insert_chunk_q = """
    INSERT INTO transcript_chunks (start_end_lines, chunk_id, transcript_id, chunk_text, chunk_tags, embedding)
    VALUES (%s, %s, %s, %s, %s, %s::vector)
    ON CONFLICT (chunk_id, transcript_id) DO NOTHING
    """

    rows = []
    for idx, chunk in enumerate(chunks_to_insert):
        emb = all_embeddings[idx]
        emb_literal = embedding_to_pgvector_literal(emb)
        rows.append((chunk["start_end"], chunk["chunk_id"],
                    chunk["transcript_id"], chunk["text"], chunk["tags"], emb_literal))

        if len(rows) >= INSERT_BATCH:
            execute_batch(cur, insert_chunk_q, rows)
            conn.commit()
            print(f"Inserted {idx + 1}/{len(chunks_to_insert)} chunks")
            rows = []

    if rows:
        execute_batch(cur, insert_chunk_q, rows)
        conn.commit()
        print(f"Inserted final {len(rows)} chunks")

    # ========== INSERT INTO transcript_embeddings TABLE ==========
    print(f"\nPreparing transcript_embeddings for {len(transcript_full_text)} transcripts...")
    
    # Prepare data for transcript_embeddings
    transcript_embedding_data = []
    for tid, full_text in transcript_full_text.items():
        metadata = transcript_metadata.get(tid, {})
        domain = metadata.get("domain")
        intent = metadata.get("intent")
        issue = metadata.get("issue_categories")
        issue_arr = [issue] if issue else None
        
        transcript_embedding_data.append({
            "transcript_id": tid,
            "transcript_text": full_text,
            "domain": domain,
            "intent": intent,
            "issue_categories": issue_arr
        })
    
    # Generate embeddings for full transcripts
    print(f"Encoding {len(transcript_embedding_data)} full transcript texts...")
    full_texts = [d["transcript_text"] for d in transcript_embedding_data]
    transcript_embeddings = []
    
    for i in range(0, len(full_texts), ENCODE_BATCH):
        batch_texts = full_texts[i:i + ENCODE_BATCH]
        batch_embs = model.encode(batch_texts, show_progress_bar=True)
        batch_embs = [np.asarray(e).tolist() for e in batch_embs]
        transcript_embeddings.extend(batch_embs)
        print(
            f"Encoded transcript batch {i // ENCODE_BATCH + 1} / {(len(full_texts) + ENCODE_BATCH - 1) // ENCODE_BATCH}")
    
    # Insert into transcript_embeddings table
    insert_transcript_embedding_q = """
    INSERT INTO transcript_embeddings (transcript_id, transcript_text, doin, intent, issue_categories, embedding)
    VALUES (%s, %s, %s, %s, %s, %s::vector)
    ON CONFLICT (transcript_id) DO NOTHING
    """
    
    rows = []
    for idx, data in enumerate(transcript_embedding_data):
        emb = transcript_embeddings[idx]
        emb_literal = embedding_to_pgvector_literal(emb)
        rows.append((
            data["transcript_id"],
            data["transcript_text"],
            data["domain"],  # doin column maps to domain
            data["intent"],
            data["issue_categories"],
            emb_literal
        ))
        
        if len(rows) >= INSERT_BATCH:
            execute_batch(cur, insert_transcript_embedding_q, rows)
            conn.commit()
            print(f"Inserted {idx + 1}/{len(transcript_embedding_data)} transcript embeddings")
            rows = []
    
    if rows:
        execute_batch(cur, insert_transcript_embedding_q, rows)
        conn.commit()
        print(f"Inserted final {len(rows)} transcript embeddings")
    
    print(f"Inserted all {len(transcript_embedding_data)} transcript embeddings")

    print("\nCreating indexes...")

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_transcripts_domain ON transcripts (domain);")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_transcripts_intent ON transcripts (intent);")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_transcripts_domain_intent ON transcripts (domain, intent);")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_transcripts_issue_categories ON transcripts USING GIN (issue_categories);")
    conn.commit()
    print("Created transcript indexes")

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_transcript_chunks_transcript_id ON transcript_chunks (transcript_id);")
    conn.commit()
    print("Created transcript_id index")

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_transcript_chunks_embedding ON transcript_chunks 
        USING hnsw (embedding vector_cosine_ops) 
        WITH (m = 32, ef_construction = 200);
    """)
    conn.commit()
    print("Created HNSW vector index for transcript_chunks")

    # Create HNSW index for transcript_embeddings
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_transcript_embeddings_embedding ON transcript_embeddings 
        USING hnsw (embedding vector_cosine_ops) 
        WITH (m = 32, ef_construction = 200);
    """)
    conn.commit()
    print("Created HNSW vector index for transcript_embeddings")

    cur.execute("""
        DO $$ 
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'transcript_chunks' AND column_name = 'text_search_vector'
            ) THEN
                ALTER TABLE transcript_chunks 
                ADD COLUMN text_search_vector tsvector 
                GENERATED ALWAYS AS (to_tsvector('english', chunk_text)) STORED;
            END IF;
        END $$;
    """)
    conn.commit()
    print("Added text_search_vector column")

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_transcript_chunks_search ON transcript_chunks USING GIN(text_search_vector);")
    conn.commit()
    print("Created text search GIN index")

    cur.close()
    conn.close()
    print("Database loading complete!")


if __name__ == "__main__":
    main()