# EvHub AI Assistant — Repository Overview

This is a shared team repository. Each branch contains a separate component of the EvHub AI assistant system.

---

## My contribution — PDF Error Code Adapter (`ev-pdf-codes-adapter/`)

**Branch:** `feature/pdf-codes-adapter`

I built the PDF codes adapter from scratch. It reads EV and hybrid vehicle service manuals (PDFs), extracts DTC (Diagnostic Trouble Code) error codes, and outputs structured JSON ready for import into a database and semantic search system.

### What it does

- Reads PDF service manuals using PyMuPDF (`fitz`)
- Detects whether the PDF is digital text or a scanned image
- Locates the DTC index table and extracts all error code records
- Handles edge cases: merged table cells, codes spanning multiple pages, layout noise
- Outputs structured JSON with vehicle info, code blocks, sections, tables, and images
- Tested on real EV workshop manuals — extracted 204 codes correctly from a Nissan Leaf manual

### How to run it

```bash
cd ev-pdf-codes-adapter
pip install -r requirements.txt

# Run on a single PDF
python src/pipeline.py manuals/EVB.pdf

# Run on all PDFs in the manuals/ folder
python src/pipeline.py

# Slim output (strips debug fields, ready for importer)
python src/pipeline.py manuals/EVB.pdf --slim
```

Output is written to `data/<manual_name>/<manual_name>.json`.

### Project structure

```
ev-pdf-codes-adapter/
  src/              # Pipeline source files
  manuals/          # Sample PDF manuals for testing
  examples/         # Example JSON outputs
  schemas/          # Output JSON schema
  docs/             # Architecture diagrams and documentation
```

Full documentation: [ev-pdf-codes-adapter/README.md](ev-pdf-codes-adapter/README.md)

---

## Other components (other branches)

| Branch | Component |
|--------|-----------|
| `main` | ev-site-crawler — web crawler for automotive content sites |
| `1-pdf-cars` | PDF cars adapter (colleague) |
| `feature/manual-pdf-multimodal-pipeline` | Multimodal PDF pipeline (colleague) |
| `Odoo` | Odoo integration (colleague) |

---

*Stack: Python 3, PyMuPDF, pathlib, hashlib. Database importer and Claude API enrichment step planned.*
