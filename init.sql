CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS transcripts (
    transcript_id VARCHAR PRIMARY KEY,
    domain VARCHAR,
    intent VARCHAR,
    issue_categories TEXT[],
    timestamp TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transcript_chunks (
    start_end_lines TEXT,
    chunk_id INTEGER,
    transcript_id VARCHAR REFERENCES transcripts(transcript_id) ON DELETE CASCADE,
    chunk_text TEXT,
    chunk_tags TEXT[],
    embedding VECTOR(768),    
    PRIMARY KEY (chunk_id, transcript_id)
);


CREATE TABLE IF NOT EXISTS transcript_embeddings (
    transcript_id VARCHAR REFERENCES transcripts(transcript_id) ON DELETE CASCADE,
    transcript_text TEXT,
    doin VARCHAR,
    intent VARCHAR,
    issue_categories TEXT[],
    embedding VECTOR(768),
    PRIMARY KEY (transcript_id)
);