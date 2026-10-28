"""The divisions the demo can answer for, and the documents each one owns.

One row per division, and this file is the one list of documents: the app,
the index build and the download script all read it. Adding a division or a
document is a row here plus a row in docs/source-documents/SOURCES.md (a test
checks the two agree), then, from the repo root:

    py hosted/scripts/fetch_documents.py    download the PDFs into hosted/documents/<id>/
    py -m prototype.ingest                 rebuild hosted/index/, tagging each chunk with its division's `id`

`file` is the document's file name in hosted/documents/<division id>/ (the
index build falls back to DATA_DIR, default data/, for older checkouts). The
PDFs are not committed: `url` is the public copy (NCDOT, FHWA or govinfo) the download script
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
            # DAR-621 stress test: public NCDOT, FHWA and CFR documents filed under this division by topic
            # (docs/stress-test-50-documents.md).
            Document(
                file="WZSafetyAndMobilityGuidelines.pdf",
                title="NCDOT Guidelines for Implementation of the Work Zone Safety and Mobility Policy (Planning, Design, Construction & Maintenance)",
                url="https://connect.ncdot.gov/projects/WZTC/Documents/WZSafetyAndMobilityGuidelines.pdf",
            ),
            Document(
                file="GLWZSIG.pdf",
                title="NCDOT Guidelines for Determining Work Zone Level of Significance (2018)",
                url="https://connect.ncdot.gov/projects/WZTC/Documents/GLWZSIG.pdf",
            ),
            Document(
                file="Work Zone - Guidelines on the Use of Positive Protection Device Memo.pdf",
                title="NCDOT TMSD Memo: Guidelines on the Use of Positive Protection Devices in Work Zones (Dec 30, 2025)",
                url="https://connect.ncdot.gov/resources/safety/Teppl/TEPPL%20All%20Documents%20Library/Work%20Zone%20-%20Guidelines%20on%20the%20Use%20of%20Positive%20Protection%20Device%20Memo.pdf",
            ),
            Document(
                file="SOP 10-9 Flagging traffic.pdf",
                title="NCDOT Safe Operating Procedure SOP 10-9: Flagging Traffic (Rev. 5, July 2026)",
                url="https://connect.ncdot.gov/business/safety/sops/SOP%2010-9%20Flagging%20traffic.pdf",
            ),
            Document(
                file="Division 11 Combined.pdf",
                title="NCDOT 2024 Roadway Standard Drawings, Division 11: Work Zone Traffic Control (combined)",
                url="https://connect.ncdot.gov/resources/Specifications/2024StandardRdwyDrawings/Division%2011%20Combined.pdf",
            ),
            Document(
                file="2024 Standard Specifications for Roads and Structures.pdf",
                title="NCDOT Standard Specifications for Roads and Structures (January 2024)",
                url="https://connect.ncdot.gov/resources/Specifications/2024StandardSpecifications/2024%20Standard%20Specifications%20for%20Roads%20and%20Structures.pdf",
            ),
            Document(
                file="Chapter_2.pdf",
                title="NCDOT Maintenance/Utility Traffic Control Guidelines (MUTCG), Chapter 2: Flagging and Other Traffic Control Measures",
                url="https://connect.ncdot.gov/projects/WZTC/Documents/Chapter_2.pdf",
            ),
            Document(
                file="Chapter_5.pdf",
                title="NCDOT Maintenance/Utility Traffic Control Guidelines (MUTCG), Chapter 5: Work Operations / Construction & Maintenance Activities",
                url="https://connect.ncdot.gov/projects/WZTC/Documents/Chapter_5.pdf",
            ),
            Document(
                file="2023 WZ Safety & Mobility Process Review.pdf",
                title="NCDOT Work Zone Safety & Mobility Process Review (December 2023)",
                url="https://connect.ncdot.gov/projects/WZTC/Documents/2023%20WZ%20Safety%20%26%20Mobility%20Process%20Review.pdf",
            ),
            Document(
                file="NCDOTFinalRuleImplementation.pdf",
                title="NCDOT Implementation of the FHWA Final Rule on Work Zone Safety & Mobility, 23 CFR 630 Subparts J & K (updated Sept 30, 2019)",
                url="https://connect.ncdot.gov/projects/wztc/Documents/NCDOTFinalRuleImplementation.pdf",
            ),
            Document(
                file="part6.pdf",
                title="MUTCD 11th Edition (December 2023), Part 6: Temporary Traffic Control",
                url="https://mutcd.fhwa.dot.gov/pdfs/11th_Edition/part6.pdf",
            ),
            Document(
                file="bpguidebook.pdf",
                title="Work Zone Operations Best Practices Guidebook, Third Edition (FHWA-HOP-13-012, 2013)",
                url="https://ops.fhwa.dot.gov/wz/practices/best/documents/bpguidebook.pdf",
            ),
            Document(
                file="rule_guide.pdf",
                title="Implementing the Rule on Work Zone Safety and Mobility (FHWA-HOP-05-065, September 2005)",
                url="https://ops.fhwa.dot.gov/wz/rule_guide/rule_guide.pdf",
            ),
            Document(
                file="trans_mgmt_plans.pdf",
                title="Developing and Implementing Transportation Management Plans for Work Zones (FHWA-HOP-05-066, December 2005)",
                url="https://ops.fhwa.dot.gov/wz/resources/publications/trans_mgmt_plans/trans_mgmt_plans.pdf",
            ),
            Document(
                file="wzi_guide.pdf",
                title="Work Zone Impacts Assessment: An Approach to Assess and Manage Work Zone Safety and Mobility Impacts of Road Projects (FHWA-HOP-05-068, August 2006)",
                url="https://ops.fhwa.dot.gov/wz/resources/final_rule/wzi_guide/wzi_guide.pdf",
            ),
            Document(
                file="fhwahop14008.pdf",
                title="Work Zone Intelligent Transportation Systems Implementation Guide (FHWA-HOP-14-008, January 2014)",
                url="https://ops.fhwa.dot.gov/publications/fhwahop14008/fhwahop14008.pdf",
            ),
            Document(
                file="fhwahop12005.pdf",
                title="Work Zone Road User Costs: Concepts and Applications (FHWA-HOP-12-005, December 2011)",
                url="https://ops.fhwa.dot.gov/wz/resources/publications/fhwahop12005/fhwahop12005.pdf",
            ),
            Document(
                file="CFR-2024-title23-vol1-part630.pdf",
                title="23 CFR Part 630, Preconstruction Procedures, incl. Subpart J (Work Zone Safety and Mobility) and Subpart K (Temporary Traffic Control Devices) (revised April 1, 2024)",
                url="https://www.govinfo.gov/content/pkg/CFR-2024-title23-vol1/pdf/CFR-2024-title23-vol1-part630.pdf",
            ),
            Document(
                file="04-20340.pdf",
                title="Federal Register 69 FR 54562 (Sept 9, 2004): Work Zone Safety and Mobility Final Rule (23 CFR 630 Subpart J)",
                url="https://www.govinfo.gov/content/pkg/FR-2004-09-09/pdf/04-20340.pdf",
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
            # DAR-621 stress test: public NCDOT, FHWA and CFR documents filed under this division by topic
            # (docs/stress-test-50-documents.md).
            Document(
                file="NCDOT Utility Cost Reimbursement Guidance_8-20-2026.pdf",
                title="NCDOT Utility Cost Reimbursement Guidance (Aug 20, 2026)",
                url="https://connect.ncdot.gov/municipalities/Utilities/UtilitiesDocuments/NCDOT%20Utility%20Cost%20Reimbursement%20Guidance_8-20-2026.pdf",
            ),
            Document(
                file="Encroachment_Requirements_Involving_Excessive_Height_Direct_Bury_Poles_5-26-2026.pdf",
                title="NCDOT Encroachment Requirements Involving Excessive Height Direct Bury Poles (May 26, 2026)",
                url="https://connect.ncdot.gov/municipalities/Utilities/UtilitiesDocuments/Encroachment_Requirements_Involving_Excessive_Height_Direct_Bury_Poles_5-26-2026.pdf",
            ),
            Document(
                file="18. Utility Plans.pdf",
                title="NCDOT Roadway Design Manual Part II, Chapter 18: Utility Plans (Nov 2007)",
                url="https://connect.ncdot.gov/projects/Roadway/Roadway%20Design%20Manual/18.%20Utility%20Plans.pdf",
            ),
            Document(
                file="09. Right of Way.pdf",
                title="NCDOT Roadway Design Manual Part II, Chapter 9: Right of Way (Rev. 4, July 2007)",
                url="https://connect.ncdot.gov/projects/Roadway/Roadway%20Design%20Manual/09.%20Right%20of%20Way.pdf",
            ),
            Document(
                file="UtilitiesCoordination-Encroachments-presentation-notes.pdf",
                title="NCDOT Utilities Coordination and Encroachments Webinar, slides with speaker notes (Aug 2017)",
                url="https://connect.ncdot.gov/projects/Project-Management/TrainingDocs/UtilitiesCoordination-Encroachments-presentation-notes.pdf",
            ),
            Document(
                file="DOT Encroachment Submissions User Manual - July 2023.pdf",
                title="NCDOT Encroachment Submissions User Guide (July 2023)",
                url="https://connect.ncdot.gov/municipalities/Utilities/UtilitiesDocuments/DOT%20Encroachment%20Submissions%20User%20Manual%20-%20July%202023.pdf",
            ),
            Document(
                file="Utility-Encroachment-Plan-Requirements.pdf",
                title="NCDOT Standard Utility Encroachment Plan Requirements (July 2023)",
                url="https://connect.ncdot.gov/municipalities/Utilities/EncroachmentForms/Utility-Encroachment-Plan-Requirements.pdf",
            ),
            Document(
                file="16-1-Two-Party-Utility-Primary-and-Secondary-Highways-Non-C-A.pdf",
                title="NCDOT Right of Way Encroachment Agreement Form 16.1: Two-Party Utility, Primary and Secondary Highways (Non-Controlled Access)",
                url="https://connect.ncdot.gov/municipalities/Utilities/EncroachmentForms/16-1-Two-Party-Utility-Primary-and-Secondary-Highways-Non-C-A.pdf",
            ),
            Document(
                file="if03014.pdf",
                title="Program Guide: Utility Relocation and Accommodation on Federal-Aid Highway Projects, Sixth Edition (FHWA-IF-03-014, January 2003)",
                url="https://www.fhwa.dot.gov/reports/utilguid/if03014.pdf",
            ),
            Document(
                file="utility_row.pdf",
                title="Utility Accommodation within Federal-aid Rights-of-Way (FHWA Office of Infrastructure presentation, April 2018)",
                url="https://www.fhwa.dot.gov/utilities/training/utility_row.pdf",
            ),
            Document(
                file="EDC-8_Factsheet_SUE.pdf",
                title="Every Day Counts (EDC-8) Fact Sheet: Subsurface Utility Engineering (SUE) (2023)",
                url="https://www.fhwa.dot.gov/innovation/everydaycounts/edc_8/pdf/EDC-8_Factsheet_SUE.pdf",
            ),
            Document(
                file="hif22002.pdf",
                title="Tech Brief: Subsurface Utility Engineering Saves Time and Costs in Delaware (FHWA-HIF-22-002)",
                url="https://www.fhwa.dot.gov/utilities/pdf/hif22002.pdf",
            ),
            Document(
                file="hif22040.pdf",
                title="Case Study: UDOT Takes Active Role in Facilitating Broadband Deployment (FHWA-HIF-22-040)",
                url="https://www.fhwa.dot.gov/utilities/pdf/hif22040.pdf",
            ),
            Document(
                file="010604.pdf",
                title="Highway/Utility Guide (FHWA-SA-93-049, June 1993)",
                url="https://www.fhwa.dot.gov/utilities/pdf/010604.pdf",
            ),
            Document(
                file="09utilcoordcert.pdf",
                title="Federal-aid Essentials Companion Guide: Utility Coordination and Certification Requirements (August 2012)",
                url="https://www.fhwa.dot.gov/federal-aidessentials/companionresources/09utilcoordcert.pdf",
            ),
            Document(
                file="fhwahop09021.pdf",
                title="Rural Interstate Corridor Communications Study: Report to States (FHWA-HOP-09-021, February 2009)",
                url="https://ops.fhwa.dot.gov/publications/fhwahop09021/fhwahop09021.pdf",
            ),
            Document(
                file="CFR-2024-title23-vol1-part645.pdf",
                title="23 CFR Part 645, Utilities (Subpart A Utility Relocations, Adjustments and Reimbursement; Subpart B Accommodation of Utilities) (revised April 1, 2024)",
                url="https://www.govinfo.gov/content/pkg/CFR-2024-title23-vol1/pdf/CFR-2024-title23-vol1-part645.pdf",
            ),
            Document(
                file="CFR-2024-title23-vol1-part710.pdf",
                title="23 CFR Part 710, Right-of-Way and Real Estate (revised April 1, 2024)",
                url="https://www.govinfo.gov/content/pkg/CFR-2024-title23-vol1/pdf/CFR-2024-title23-vol1-part710.pdf",
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
            # DAR-621 stress test: public NCDOT, FHWA and CFR documents filed under this division by topic
            # (docs/stress-test-50-documents.md).
            Document(
                file="Policy on Access Manual.pdf",
                title="NCDOT Policy on Street and Driveway Access to North Carolina Highways (July 2003)",
                url="https://connect.ncdot.gov/resources/safety/Teppl/TEPPL%20All%20Documents%20Library/Policy%20on%20Access%20Manual.pdf",
            ),
            Document(
                file="Signal System Timing Philosophy Manual.pdf",
                title="NCDOT Signal System Timing Philosophy Manual, Version 2.0 (Feb 1, 2017)",
                url="https://connect.ncdot.gov/resources/safety/Teppl/TEPPL%20All%20Documents%20Library/Signal%20System%20Timing%20Philosophy%20Manual.pdf",
            ),
            Document(
                file="L18_TSLG_Guide.pdf",
                title="NCDOT Traffic Services Legal Guide (revised June 20, 2023)",
                url="https://connect.ncdot.gov/resources/safety/Teppl/TEPPL%20All%20Documents%20Library/L18_TSLG_Guide.pdf",
            ),
            Document(
                file="C34 - Manual 2012.pdf",
                title="NCDOT DMV-349 Crash Report Instructional Manual (revised Aug 24, 2012)",
                url="https://connect.ncdot.gov/resources/safety/Teppl/TEPPL%20All%20Documents%20Library/C34%20-%20Manual%202012.pdf",
            ),
            Document(
                file="03. Guardrail, Barriers and Attenuators.pdf",
                title="NCDOT Roadway Design Manual Part I, Chapter 3: Guardrail, Barriers and Attenuators",
                url="https://connect.ncdot.gov/projects/Roadway/Roadway%20Design%20Manual/03.%20Guardrail%2C%20Barriers%20and%20Attenuators.pdf",
            ),
            Document(
                file="09. At Grade Intersections.pdf",
                title="NCDOT Roadway Design Manual Part I, Chapter 9: At Grade Intersections (Rev. 3, 2004)",
                url="https://connect.ncdot.gov/projects/Roadway/Roadway%20Design%20Manual/09.%20At%20Grade%20Intersections.pdf",
            ),
            Document(
                file="bikeped_Ped_Policy.pdf",
                title="NCDOT Pedestrian Policy Guidelines, Policy and Procedure Manual Chapter 28: Sidewalks (rev. Apr 16, 2001)",
                url="https://connect.ncdot.gov/projects/BikePed/Documents/bikeped_Ped_Policy.pdf",
            ),
            Document(
                file="interim-design-safety-pilot-program.pdf",
                title="NCDOT Interim Design Safety Pilot Project Final Report (September 2023)",
                url="https://connect.ncdot.gov/projects/BikePed/Documents/interim-design-safety-pilot-program.pdf",
            ),
            Document(
                file="fhwa_hop_08_024.pdf",
                title="Traffic Signal Timing Manual (FHWA-HOP-08-024, June 2008)",
                url="https://ops.fhwa.dot.gov/publications/fhwahop08024/fhwa_hop_08_024.pdf",
            ),
            Document(
                file="Chapter2c.pdf",
                title="MUTCD 11th Edition (December 2023), Chapter 2C: Warning Signs and Object Markers",
                url="https://mutcd.fhwa.dot.gov/pdfs/11th_Edition/Chapter2c.pdf",
            ),
            Document(
                file="part3.pdf",
                title="MUTCD 11th Edition (December 2023), Part 3: Markings",
                url="https://mutcd.fhwa.dot.gov/pdfs/11th_Edition/part3.pdf",
            ),
            Document(
                file="01102.pdf",
                title="Pedestrian Facilities Users Guide: Providing Safety and Mobility (FHWA-RD-01-102)",
                url="https://www.fhwa.dot.gov/publications/research/safety/01102/01102.pdf",
            ),
            Document(
                file="04100.pdf",
                title="Safety Effects of Marked Versus Unmarked Crosswalks at Uncontrolled Locations: Final Report and Recommended Guidelines (FHWA-HRT-04-100, September 2005)",
                url="https://www.fhwa.dot.gov/publications/research/safety/04100/04100.pdf",
            ),
            Document(
                file="STEP-guide-improving-ped-safety.pdf",
                title="Guide for Improving Pedestrian Safety at Uncontrolled Crossing Locations (FHWA STEP, July 2018, updated)",
                url="https://www.fhwa.dot.gov/innovation/everydaycounts/edc_5/docs/STEP-guide-improving-ped-safety.pdf",
            ),
            Document(
                file="04091.pdf",
                title="Signalized Intersections: Informational Guide (FHWA-HRT-04-091, August 2004)",
                url="https://www.fhwa.dot.gov/publications/research/safety/04091/04091.pdf",
            ),
            Document(
                file="CFR-2024-title23-vol1-part924.pdf",
                title="23 CFR Part 924, Highway Safety Improvement Program (revised April 1, 2024)",
                url="https://www.govinfo.gov/content/pkg/CFR-2024-title23-vol1/pdf/CFR-2024-title23-vol1-part924.pdf",
            ),
            Document(
                file="CFR-2024-title23-vol1-part655.pdf",
                title="23 CFR Part 655, Traffic Operations (MUTCD adoption) (revised April 1, 2024)",
                url="https://www.govinfo.gov/content/pkg/CFR-2024-title23-vol1/pdf/CFR-2024-title23-vol1-part655.pdf",
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
