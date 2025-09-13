CREATE TABLE IF NOT EXISTS documents (
  doc_id SERIAL PRIMARY KEY,
  celex  TEXT NOT NULL,
  title  TEXT,
  eli_uri TEXT,
  doc_type TEXT,
  lang TEXT DEFAULT 'en',
  date DATE,
  hash TEXT
);
CREATE TABLE IF NOT EXISTS spans (
  span_id SERIAL PRIMARY KEY,
  doc_id  INT REFERENCES documents(doc_id) ON DELETE CASCADE,
  ref_label TEXT NOT NULL,
  article TEXT,
  annex TEXT,
  paragraph TEXT,
  text TEXT NOT NULL,
  start_char INT,
  end_char INT
);
CREATE INDEX IF NOT EXISTS idx_spans_ref_label ON spans(ref_label);
CREATE INDEX IF NOT EXISTS idx_spans_article_para ON spans(article, paragraph);
