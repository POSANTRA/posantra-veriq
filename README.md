# POSANTRA | VERIQ

**Detect. Investigate. Verify.**

*Digital Content Verification & Intelligence Platform*
Parent organisation: **POSANTRA** — *Understand. Investigate. Protect.*

VERIQ is an evidence-driven investigation tool for images and public social-media
posts. It does **not** claim to know whether something is "real" or "fake". It shows what
was investigated, what evidence was found and not found, what technical indicators
exist, and what limitations apply.

> Status: Phase 1 MVP. It runs locally, costs nothing, and has been tested with
> automated tests. It has **not** been validated against a large set of real-world
> images or live platforms, and it is not a substitute for professional forensic work.

---

## What it does (Implemented)

### Image investigation
- Upload validation: size limit, extension allow-list, real content-type detection
  from file bytes, extension/content match, filename sanitising, full decode check,
  pixel-count (decompression-bomb) limit.
- Media information and SHA-256.
- Metadata via **ExifTool** (fixed-argument call, no shell), with a limited Pillow
  fallback. Found and absent metadata are shown separately. GPS is shown only if
  embedded, and is always labelled unreliable and not the uploader's location.
- **Content Credentials (C2PA)** summary: reports what an embedded manifest *claims*.
  The signature is **not** cryptographically validated.
- **OCR** with Tesseract (English), labelled "Extracted text", with confidence.
- **Forensic indicators** (not proof): JPEG quantization estimate, chroma subsampling,
  encoding mode, Error Level Analysis with heatmap (JPEG only), PNG generator-chunk
  names. Inapplicable checks say "Not applicable".
- **Fingerprints**: SHA-256, aHash, pHash, dHash, and comparison against images this
  installation has already analysed (opt-in, hashes only).
- **Assessment** using the six fixed categories with evidence-strength wording
  (no percentages).

### Post URL investigation
- Strict URL validation, platform detection, SSRF guard (private/local addresses
  blocked, every redirect hop re-checked, size and time limits).
- Retrieval only through what a site publicly serves: public oEmbed (X, YouTube,
  TikTok) and Open Graph link-preview tags. **No login, no bypassing, no scraping
  around blocks.** On failure it shows the fallback message and a manual text box.
- Claim candidates (rule-based), evidence search (Wikipedia and GDELT, free),
  user-recorded stances with explanations, source-tier classification, timeline,
  and a claim assessment that follows fixed rules.

### Reports and records
- "VERIQ Investigation Report": standalone HTML (open in a browser, Print, Save as
  PDF). All content is HTML-escaped; the report never contains the uploaded image.
- Opt-in saved investigation records in local SQLite, with delete-all.

---

## What it does not do

- It cannot tell real photos from AI-generated or edited ones in general. It only
  reports declared provenance, embedded metadata and weak technical indicators.
- **No reverse image search.** Earlier-publication evidence must be found manually
  (for example Google Lens or TinEye) and recorded by you.
- It does **not** automatically decide whether a source supports or contradicts a
  claim. You record the stance and a written reason; the assessment follows from that.
- It does not determine **where an uploader is**. Creation, depicted, publication and
  uploader locations are different things; only the first two can ever be hinted at
  by file data, and never reliably.
- No video, audio or deepfake analysis.
- Claim detection is English-only and crude.

## The six assessments

AUTHENTIC, MANIPULATED, MISLEADING CONTEXT, UNVERIFIED, CONTRADICTED,
INSUFFICIENT EVIDENCE. Most lone images correctly land on UNVERIFIED or
INSUFFICIENT EVIDENCE. AUTHENTIC, CONTRADICTED and MISLEADING CONTEXT require a
claim plus reliable sources (source tiers 1–6) recorded with an explanation.
MANIPULATED from an image arises only when its own embedded credentials declare AI
generation, which is a self-declared, unvalidated record.

---

## Installation (Windows)

Requirements: Python 3.10+, Git (optional), Tesseract OCR, ExifTool.

```powershell
winget install --id Git.Git -e
winget install --id UB-Mannheim.TesseractOCR -e
winget install --id OliverBetz.ExifTool -e
```

Open a **new** PowerShell window so PATH updates apply. Tesseract usually needs
`C:\Program Files\Tesseract-OCR` added to PATH. VERIQ also checks default install
locations, and you can override with `VERIQ_TESSERACT_PATH` / `VERIQ_EXIFTOOL_PATH`.

```powershell
cd E:\POSANTRA_VERIQ
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Missing tools are reported as "Not available" in the app; nothing is faked.

## Run

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests that need Tesseract or ExifTool skip themselves if those are missing. Network
calls are faked, so the suite needs no internet. `tests/test_matrix.py` runs the
specification's 18 scenarios; `tests/test_hardening.py` covers attack cases.

## Project layout

```text
app.py                  Streamlit application
config.py               branding, limits, tool discovery
modules/                analysis, retrieval, claims, verdicts, reports, UI helpers
database/               SQLite access and schema.sql
tests/                  automated tests
.streamlit/config.toml  theme and upload limit
uploads/                short-lived temporary files (emptied after each analysis)
reports/                reserved; reports are downloaded, not written here
```

## Supported input

- Images: JPG, JPEG, PNG, WebP, up to 10 MB and 50 megapixels. HEIC and GIF are not
  supported. Animated images are analysed on their first frame.
- URLs: public `http(s)` pages on ports 80/443. Facebook, Instagram, LinkedIn and
  Threads mostly require login, so expect the manual fallback there. Platform
  endpoints and markup change; retrieval can break without notice.

## Privacy

- Uploaded images are analysed locally and are never sent anywhere or stored.
- Fingerprints (hashes, sanitised file name, dimensions, timestamps) are stored only
  if the checkbox is ticked. Saved records store report data (which can include OCR
  text, post text and GPS metadata) only when you click Save. **The database is not
  encrypted.** Delete records you do not need.
- Post URL mode requests the URL from your machine, so the site can see the request.
  Evidence search sends only the visible query text to Wikipedia and GDELT, only
  when you click Search.
- Avoid uploading highly sensitive material unless necessary.

## Security measures

Untrusted-input handling for uploads and URLs: size/type/content checks, safe
random-named temporary files with guaranteed cleanup, fixed-argument subprocess
calls (no shell), SSRF guard with redirect re-validation, response size and time
limits, parameterised SQL, HTML escaping everywhere untrusted text is displayed, a
Content-Security-Policy in reports.

Known gaps: DNS rebinding is narrowed but not fully closed (the resolved address is
not pinned); robots.txt is not checked; no authentication (the app is intended for
local use on a trusted machine); no malware scanning.

## Known limitations

- Forensic indicators are weak, and ELA's "worth a closer look" threshold is an
  unvalidated rule of thumb. Source-tier domain lists are a starting set, not an
  endorsement of any outlet.
- Perceptual-hash similarity thresholds are rules of thumb.
- Evidence and claims live in the browser session until you save a record.
- The assessment is only as good as the evidence a person records.
- Not tested at scale or against live platforms over time.

## Disclaimer

VERIQ provides an evidence-based technical assessment using available information
and analytical methods. It does not guarantee absolute authenticity, manipulation,
authorship, origin, or intent. Results depend on the quality and availability of
evidence.

---

## Roadmap (Planned — **not implemented**)

**Phase 2: Video investigation.** Video upload, frame extraction, frame-level
analysis, deepfake indicators, audio analysis, audio/video consistency, video
provenance, temporal manipulation analysis.

**Possible later features:** broader reverse-image research (optional integration),
C2PA signature validation, multilingual claim analysis, provenance graphs, content
similarity networks, advanced AI-generated-media detection, browser extension, API,
enterprise deployment, analyst collaboration, case management, threat-intelligence
integrations.