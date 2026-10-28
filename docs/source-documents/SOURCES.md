# Source documents

The public NCDOT documents each division's answers are drawn from. The PDFs are not
committed: `hosted/scripts/fetch_documents.py` downloads them from these URLs into
`hosted/documents/<division id>/`, and `python -m prototype.ingest` builds the
committed index from them.

`hosted/divrag/divisions.py` is the list the app, the index build and the download
script read. This page mirrors it for people, adding each PDF's page count and the
date it was fetched; `tests/test_fetch_documents.py` fails when the two disagree, and
`python hosted/scripts/fetch_documents.py --check-sources` prints a ready-to-paste row
for any document missing here.

To add a document: add it to its division's row in `divisions.py`, add its row below,
then run the fetch script, `python -m prototype.ingest` (it prints each document's
last page), and commit `hosted/index/`.

## Work Zone Traffic Control (`wztc`)

| File | Title | Source URL | Pages | Fetched |
|---|---|---|---|---|
| `TMP Design Manual (Combined, No Links).pdf` | Work Zone Traffic Control Design Manual (TMP Design Manual) | <https://connect.ncdot.gov/projects/WZTC/Documents/TMP%20Design%20Manual%20%28Combined%2C%20No%20Links%29.pdf> | 172 | 2026-09-25 |

## Utilities (`utilities`)

| File | Title | Source URL | Pages | Fetched |
|---|---|---|---|---|
| `20220713 NCDOT UAM Ver 2-0.pdf` | Utilities Accommodation Manual, Version 2.0 (July 2022) | <https://connect.ncdot.gov/municipalities/Utilities/UtilitiesDocuments/20220713%20NCDOT%20UAM%20Ver%202-0.pdf> | 311 | 2026-10-10 |

## Transportation Mobility and Safety (`tmsd`)

Chosen from the division's Traffic Safety Manuals page,
<https://connect.ncdot.gov/resources/safety/Pages/Traffic-Safety-Manuals.aspx>.

| File | Title | Source URL | Pages | Fetched |
|---|---|---|---|---|
| `TODS Manual - September 2024.pdf` | Tourist Oriented Directional Signs (TODS) Procedures Manual (September 2024) | <https://connect.ncdot.gov/resources/safety/Teppl/TEPPL%20All%20Documents%20Library/TODS%20Manual%20-%20September%202024.pdf> | 46 | 2026-10-27 |
| `Fatal Investigation Guidelines.pdf` | Guidelines for Investigation of Fatal Crashes (October 2019) | <https://connect.ncdot.gov/resources/safety/Teppl/TEPPL%20All%20Documents%20Library/Fatal%20Investigation%20Guidelines.pdf> | 5 | 2026-10-27 |
