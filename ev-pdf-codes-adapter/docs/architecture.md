# ETL Pipeline Architecture

> Last updated: 2026-04-19

## Legend

| Colour | Meaning |
|---|---|
| 🟢 Green | Complete and working |
| 🟠 Orange | Must-have — not built yet |
| 🟡 Yellow | Nice-to-have — deferred |
| ⬜ Grey | Future phase — waiting on decision |

> **April 2026:** PostgreSQL + pgvector on AWS confirmed by lead. AWS Bedrock (LLM enrichment) confirmed but blocked by permissions — pending resolution.

---

```mermaid
flowchart TD

    %% ── INPUT ───────────────────────────────────────────────
    A([📁 manuals/*.pdf])

    %% ── ORCHESTRATOR ─────────────────────────────────────────
    subgraph ORCH["ORCHESTRATOR — pipeline.py"]
        B[Walk directory\nfind all PDFs]
        C{JSON already\nexists?}
        D([Skip])
        E[try/except per PDF\nskip and log on error]
        F[Atomic write\n.json.tmp → .json]
        G[resume_log.jsonl]
        H[processing_report.json]
    end

    %% ── ADAPTER ──────────────────────────────────────────────
    subgraph ADAPT["PER-PDF ADAPTER — extractor.py"]
        I[SHA256 → document_id]
        J[build_index\nscan first 60 pages for DTC table]
        K[Group codes by page number]

        subgraph LOOP["Per-page loop"]
            L[Extract text\nPyMuPDF]
            M[Clean text\nstrip sidebar noise]
            N[OCR fallback\nTesseract]
            O[Fix image extraction\nget_pixmap + size filter]
            P[DTC regex scan\n→ dtc_mentions]
        end

        Q[Assemble page record\nschema v1]
    end

    %% ── OUTPUT ───────────────────────────────────────────────
    R([📄 data/pdf-stem/pdf-stem.json])
    S([🖼️ data/pdf-stem/images/\npartial — fix in Phase 3])
    T([🗄️ PostgreSQL + pgvector\nAWS — confirmed by lead])

    %% ── FLOW ─────────────────────────────────────────────────
    A --> B
    B --> C
    C -->|YES| D
    C -->|NO| E
    E --> I
    I --> J
    J --> K
    K --> L
    L --> M
    M --> N
    N --> O
    O --> P
    P --> Q
    Q --> F
    F --> R
    F --> S
    S --> T
    F --> G
    F --> H

    %% ── STYLES ───────────────────────────────────────────────

    %% Green — complete
    style A fill:#2d6a4f,color:#fff,stroke:#1b4332
    style B fill:#2d6a4f,color:#fff,stroke:#1b4332
    style C fill:#2d6a4f,color:#fff,stroke:#1b4332
    style D fill:#2d6a4f,color:#fff,stroke:#1b4332
    style E fill:#2d6a4f,color:#fff,stroke:#1b4332
    style F fill:#2d6a4f,color:#fff,stroke:#1b4332
    style I fill:#2d6a4f,color:#fff,stroke:#1b4332
    style J fill:#2d6a4f,color:#fff,stroke:#1b4332
    style K fill:#2d6a4f,color:#fff,stroke:#1b4332
    style L fill:#2d6a4f,color:#fff,stroke:#1b4332
    style M fill:#2d6a4f,color:#fff,stroke:#1b4332
    style Q fill:#2d6a4f,color:#fff,stroke:#1b4332
    style R fill:#2d6a4f,color:#fff,stroke:#1b4332
    style S fill:#2d6a4f,color:#fff,stroke:#1b4332

    %% Orange — must-have, not built
    style N fill:#e76f51,color:#fff,stroke:#c1440e
    style O fill:#e76f51,color:#fff,stroke:#c1440e
    style P fill:#e76f51,color:#fff,stroke:#c1440e

    %% Yellow — nice-to-have
    style G fill:#f4a261,color:#000,stroke:#e76f51
    style H fill:#f4a261,color:#000,stroke:#e76f51

    %% Orange — must-have, not built (PostgreSQL importer confirmed, not yet built)
    style T fill:#e76f51,color:#fff,stroke:#c1440e
```

---

## Deferred ideas

### Table image rendering

Tables are currently extracted as structured JSON (`raw_rows`, `reconstructed_rows`). It is also possible to save a visual PNG snapshot of each table alongside the structured data using PyMuPDF's page region rendering:

```python
rect = table.bbox          # bounding box from page.find_tables()
pix  = page.get_pixmap(clip=rect, dpi=150)
pix.save(output_dir / f"{page_ref}-table{idx}.png")
```

This would let the importer show a human-readable view of each table, or feed it to a vision model for verification. Not needed for the current importer pipeline — deferred until there is a concrete use case.
