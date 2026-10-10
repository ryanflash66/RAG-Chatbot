"""The divisions the demo can answer for, and the documents each one owns.

One row per division. Adding a third division is one more row here plus a
rebuild of the index (`py -m prototype.ingest`, run from the repo root), which
tags every chunk of the row's documents with the row's `id`.

`file` is the document's path under the repo's data/ directory at ingest time;
the PDFs themselves are not committed. `url` is the public NCDOT copy the
answer's citations link to (with #page=N appended).
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


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
)

BY_ID: Dict[str, Division] = {d.id: d for d in DIVISIONS}


def document_for(file: str) -> Optional[Document]:
    """The configured Document whose file name matches a chunk's `source`."""
    for division in DIVISIONS:
        for document in division.documents:
            if document.file == file:
                return document
    return None
