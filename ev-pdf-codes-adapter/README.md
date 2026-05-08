\# EV Hub PDF Error Code Adapter



\## What this does

Extracts DTC (Diagnostic Trouble Code) error codes from EV/hybrid car service manuals (PDFs) and stores them for semantic search. Scale target is hundreds to thousands of manuals across 40 years of vehicles( not really sure, but lets pretend)



\## Stack



Python3

fitz(pymupdf, anthropic(not implemented yet)

pymongo(not there yet, but considering)

psycopg2(or others if we decide to use postgresql)



\## What I have done so far

\- Built a working pipeline that reads a PDF and extracts error codes

\- Tested it on EVB.pdf — found and extracted 204 codes correctly

\- It handles tricky situations like merged table cells and codes that span multiple pages

\- Cleans up the text by removing noise that comes from the PDF layout

\- Added a sample PDF and sample output so teammates can test it straight away



\## Architecture

All source files live flat in `src/`. There are no subfolders — at this scale flat is simpler and standard. The logical layers below show how the files relate to each other.

```
┌─────────────────────────────────────────────────────────┐
│  ORCHESTRATION                                          │
│  pipeline.py — entry point, runs the full pipeline      │
└───────────────────────────┬─────────────────────────────┘
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
          ▼                 ▼                 ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  INPUT          │ │  PROFILING      │ │  EXTRACTION     │
│  vehicle_info   │ │  pdf_profile    │ │  extractor      │
│                 │ │                 │ │  type_detector  │
└─────────────────┘ └─────────────────┘ └────────┬────────┘
                                                  │
                                                  ▼
                                        ┌─────────────────┐
                                        │  PYMUPDF LAYER  │
                                        │  index_builder  │
                                        │  content_       │
                                        │    extractor    │
                                        └─────────────────┘
                                                  │
                                                  ▼
                                        ┌─────────────────┐
                                        │  SUPPORT        │
                                        │  patterns       │
                                        │  text_parser    │
                                        └─────────────────┘

┌─────────────────────────────────────────────────────────┐
│  OUTPUT  (files written to data/)                       │
│  data/<stem>/<stem>.json   — extracted DTC records      │
│  data/<stem>/images/       — extracted images           │
│  data/processing_report.json — single run summary       │
│  data/run_history.json       — all runs history         │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  MANUAL TOOLS  (not part of the pipeline)               │
│  debug_table.py     — inspect PyMuPDF table detection   │
│  diag.py            — analyse pipeline output JSON      │
│  script_for_meta.py — one-off metadata extraction       │
│  docling_enricher.py — experimental Docling enrichment  │
└─────────────────────────────────────────────────────────┘
```

### What each layer does

| Layer | Files | Responsibility |
|---|---|---|
| Orchestration | `pipeline.py` | Reads args, loops over PDFs, writes JSON, saves report |
| Input | `vehicle_info.py` | Extracts vehicle make, model, year from PDF headers/footers |
| Profiling | `pdf_profile.py` | Classifies PDF as digital or scanned before extraction starts |
| Extraction | `extractor.py`, `type_detector.py` | Builds DTC records; detects TYPE N section boundaries |
| PyMuPDF layer | `index_builder.py`, `content_extractor.py` | All direct fitz calls — index scanning, page reading, table detection |
| Support | `patterns.py`, `text_parser.py` | Shared regex patterns and text utilities used across layers |
| Output | *(data/ folder)* | JSON records, images, run reports — written by pipeline.py |
| Manual Tools | `debug_table.py`, `diag.py`, `script_for_meta.py`, `docling_enricher.py` | Debug and diagnostic scripts — run manually, not part of the pipeline |

## What I am working on next

\- Make the pipeline scan a whole folder of PDFs automatically instead of one at a time

\- Test it on many PDFs from different folders and subfolders

\- Decide how to save the output — waiting on team decision (see blockers)  

\- Build the database importer once the team decides on storage

\- Add Claude AI cleanup for records that are missing content



\## Known limitations (things that might go wrong)

\- If a PDF is a scanned image (not real text) the extractor 

&#x20; will not find any content — fitz can only read real text

\- If the PDF does not have a DTC index table the pipeline 

&#x20; will find zero codes

\- Messy or incomplete text in records is expected — 

&#x20; Claude API cleanup will handle this later

\- Only tested on one manual so far (EVB.pdf, Nissan 2013) — 

&#x20; other manufacturers may have different layouts that need adjusting



\## Open questions for the team

\- Are we using PostgreSQL as the database? Still not confirmed

\- Where will we store the full collection of manuals? (Google Drive, shared server?)

\- Does the Claude cleanup happen inside this adapter or somewhere else in the system?

\- I do not have Claude API access yet — currently testing cleanup manually by chatting with Claude Pro



\## Blockers (things I am stuck on and need help with)

\- Nobody has decided yet if we are using PostgreSQL or MongoDB 

&#x20; to save the data — I need to know this before I can build 

&#x20; the database importer

\- No decision on how to organise the JSON output folder — 

&#x20; should data/ mirror the manuals/ folder structure 

&#x20; (e.g. manuals/nissan/2013/EVB.pdf → data/nissan/2013/EVB.json) 

&#x20; or save everything flat in one folder?

\- I do not have a Claude API key yet — I need this to build 

&#x20; the cleanup step, for now I am testing manually by chatting 

&#x20; with Claude Pro

\- Is the current JSON output structure good enough for the 

&#x20; rest of the team? Nobody has confirmed if the schema is 

&#x20; correct yet



\## How to run it

Make sure you have the libraries installed:

* pip install -r requirements.txt

Then run it on a PDF:

* python src/pipeline.py manuals/EVB.pdf

The output will be saved to data/EVB/EVB.json

To process all PDFs in the manuals/ folder at once:

* python src/pipeline.py

To reprocess a PDF that has already been extracted:

* python src/pipeline.py manuals/EVB.pdf --force

\## Output modes

By default the pipeline writes the full output including raw debug fields.

Use --slim to produce lean output for the importer (strips raw\_text, raw\_table\_text, and ocr\_used):

* python src/pipeline.py manuals/EVB.pdf --slim
* python src/pipeline.py --slim

Full output (default) — keeps all raw fields. Use this when developing or debugging the adapter.

Slim output (--slim) — removes noisy/redundant fields. Use this when the output will be handed to the importer for sanitization, enrichment, embedding, and storage.

