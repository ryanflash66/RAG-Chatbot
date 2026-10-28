"""The divisions the demo can answer for, and the documents each one owns.

One row per division, and this file is the one list of documents: the app,
the index build and the download script all read it. Adding a division or a
document is a row here plus a row in docs/source-documents/SOURCES.md (a test
checks the two agree), then, from the repo root:

    py hosted/scripts/fetch_documents.py    download the PDFs into hosted/documents/<id>/
    py -m prototype.ingest                 rebuild hosted/index/, tagging each chunk with its division's `id`

`file` is the document's file name in hosted/documents/<division id>/ (the
index build falls back to DATA_DIR, default data/, for older checkouts). The
PDFs are not committed: `url` is the public NCDOT copy the download script
fetches and the answer's citations link to (with #page=N appended). File names
must be unique across divisions, since a chunk's `source` is its file name.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

# Where the index build reads each division's documents, one folder per division id.
# Not part of the deployed app: the folder is gitignored and left out of Vercel uploads.
DOCUMENTS_DIR = Path(__file__).resolve().parent.parent / "documents"


@dataclass(frozen=True)
class Document:
    file: str
    title: str
    url: str


@dataclass(frozen=True)
class Division:
    id: str
    name: str
    unit: str
    documents: Tuple[Document, ...]
    # Clickable example questions shown when this division is the one being asked.
    examples: Tuple[str, ...] = ()


DIVISIONS: Tuple[Division, ...] = (
    Division(
        id="wztc",
        name="Work Zone Traffic Control",
        unit="NCDOT Work Zone Traffic Control Section",
        documents=(
            Document(
                file="TMP Design Manual (Combined, No Links).pdf",
                title="Work Zone Traffic Control Design Manual (TMP Design Manual)",
                url="https://connect.ncdot.gov/projects/WZTC/Documents/TMP%20Design%20Manual%20%28Combined%2C%20No%20Links%29.pdf",
            ),
        ),
        examples=(
            "What are the dimensions of the NC-PCB concrete barrier?",
            "What is the minimum acceleration lane for an interstate entrance ramp in a work zone?",
            "What lane width is used on a freeway or divided highway work zone?",
            "When must portable concrete barrier on a bridge deck be anchored?",
        ),
    ),
    Division(
        id="utilities",
        name="Utilities",
        unit="NCDOT Utilities Unit",
        documents=(
            Document(
                file="20220713 NCDOT UAM Ver 2-0.pdf",
                title="Utilities Accommodation Manual, Version 2.0 (July 2022)",
                url="https://connect.ncdot.gov/municipalities/Utilities/UtilitiesDocuments/20220713%20NCDOT%20UAM%20Ver%202-0.pdf",
            ),
        ),
        examples=(
            "At what distance from a travel lane does utility work require a lane closure?",
            "Who pays for a detour when a utility closes a road?",
            "What is the minimum cover for a utility installed by bore and jack?",
            "If utility work blocks a sidewalk for 7 work days or more, what is required?",
        ),
    ),
    # From the Traffic Safety Manuals page (https://connect.ncdot.gov/resources/safety/Pages/Traffic-Safety-Manuals.aspx),
    # two documents whose covers name the division, on topics the other two manuals don't cover: TODS
    # signing for businesses and the fatal crash location investigations of its Traffic Safety Unit.
    Division(
        id="tmsd",
        name="Transportation Mobility and Safety",
        unit="NCDOT Transportation Mobility and Safety Division",
        documents=(
            Document(
                file="TODS Manual - September 2024.pdf",
                title="Tourist Oriented Directional Signs (TODS) Procedures Manual (September 2024)",
                url="https://connect.ncdot.gov/resources/safety/Teppl/TEPPL%20All%20Documents%20Library/TODS%20Manual%20-%20September%202024.pdf",
            ),
            Document(
                file="Fatal Investigation Guidelines.pdf",
                title="Guidelines for Investigation of Fatal Crashes (October 2019)",
                url="https://connect.ncdot.gov/resources/safety/Teppl/TEPPL%20All%20Documents%20Library/Fatal%20Investigation%20Guidelines.pdf",
            ),
        ),
        examples=(
            "How many TODS panels can go on one intersection approach?",
            "How long does an attraction have to change its operation to qualify for TODS?",
            "What fees does an attraction pay for a TODS sign?",
            "How long does a regional office have to complete a fatal crash investigation?",
        ),
    ),
)

BY_ID: Dict[str, Division] = {d.id: d for d in DIVISIONS}


def document_for(file: str) -> Optional[Document]:
    """The configured Document whose file name matches a chunk's `source`."""
    for division in DIVISIONS:
        for document in division.documents:
            if document.file == file:
                return document
    return None
