# Source documents

The public documents each division's answers are drawn from: NCDOT manuals, plus
(since the 50-document stress test, `docs/stress-test-50-documents.md`) FHWA
publications and 23 CFR parts from govinfo, each filed under the division whose topic
it covers. The PDFs are not committed: `hosted/scripts/fetch_documents.py` downloads them from these URLs into
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

No Office of Federal Lands Highway document is listed: every FLH manual (the Project
Development and Design Manual chapters, FP-24) is served from highways.dot.gov, which
answered scripted downloads with 403 Access Denied on 2026-10-27, so the fetch script
could not rebuild the index from them.

Two scanned PDFs from the stress test are left out because they have no text layer, so
they produce no passages and could never be cited: the NCDOT Work Zone Safety and
Mobility Policy (<https://connect.ncdot.gov/projects/WZTC/Documents/WZSafety_and_Mobility.pdf>)
and the Revised Rumble Strip Guidelines
(<https://connect.ncdot.gov/resources/safety/Teppl/TEPPL%20All%20Documents%20Library/Revised%20Rumble%20Strip%20Guidelines.pdf>).
Add them back once they are OCR'd.

## Work Zone Traffic Control (`wztc`)

| File | Title | Source URL | Pages | Fetched |
|---|---|---|---|---|
| `TMP Design Manual (Combined, No Links).pdf` | Work Zone Traffic Control Design Manual (TMP Design Manual) | <https://connect.ncdot.gov/projects/WZTC/Documents/TMP%20Design%20Manual%20%28Combined%2C%20No%20Links%29.pdf> | 172 | 2026-09-25 |
| `WZSafetyAndMobilityGuidelines.pdf` | NCDOT Guidelines for Implementation of the Work Zone Safety and Mobility Policy (Planning, Design, Construction & Maintenance) | <https://connect.ncdot.gov/projects/WZTC/Documents/WZSafetyAndMobilityGuidelines.pdf> | 26 | 2026-10-27 |
| `GLWZSIG.pdf` | NCDOT Guidelines for Determining Work Zone Level of Significance (2018) | <https://connect.ncdot.gov/projects/WZTC/Documents/GLWZSIG.pdf> | 1 | 2026-10-27 |
| `Work Zone - Guidelines on the Use of Positive Protection Device Memo.pdf` | NCDOT TMSD Memo: Guidelines on the Use of Positive Protection Devices in Work Zones (Dec 30, 2025) | <https://connect.ncdot.gov/resources/safety/Teppl/TEPPL%20All%20Documents%20Library/Work%20Zone%20-%20Guidelines%20on%20the%20Use%20of%20Positive%20Protection%20Device%20Memo.pdf> | 2 | 2026-10-27 |
| `SOP 10-9 Flagging traffic.pdf` | NCDOT Safe Operating Procedure SOP 10-9: Flagging Traffic (Rev. 5, July 2026) | <https://connect.ncdot.gov/business/safety/sops/SOP%2010-9%20Flagging%20traffic.pdf> | 2 | 2026-10-27 |
| `Division 11 Combined.pdf` | NCDOT 2024 Roadway Standard Drawings, Division 11: Work Zone Traffic Control (combined) | <https://connect.ncdot.gov/resources/Specifications/2024StandardRdwyDrawings/Division%2011%20Combined.pdf> | 59 | 2026-10-27 |
| `2024 Standard Specifications for Roads and Structures.pdf` | NCDOT Standard Specifications for Roads and Structures (January 2024) | <https://connect.ncdot.gov/resources/Specifications/2024StandardSpecifications/2024%20Standard%20Specifications%20for%20Roads%20and%20Structures.pdf> | 857 | 2026-10-27 |
| `Chapter_2.pdf` | NCDOT Maintenance/Utility Traffic Control Guidelines (MUTCG), Chapter 2: Flagging and Other Traffic Control Measures | <https://connect.ncdot.gov/projects/WZTC/Documents/Chapter_2.pdf> | 48 | 2026-10-27 |
| `Chapter_5.pdf` | NCDOT Maintenance/Utility Traffic Control Guidelines (MUTCG), Chapter 5: Work Operations / Construction & Maintenance Activities | <https://connect.ncdot.gov/projects/WZTC/Documents/Chapter_5.pdf> | 93 | 2026-10-27 |
| `2023 WZ Safety & Mobility Process Review.pdf` | NCDOT Work Zone Safety & Mobility Process Review (December 2023) | <https://connect.ncdot.gov/projects/WZTC/Documents/2023%20WZ%20Safety%20%26%20Mobility%20Process%20Review.pdf> | 10 | 2026-10-27 |
| `NCDOTFinalRuleImplementation.pdf` | NCDOT Implementation of the FHWA Final Rule on Work Zone Safety & Mobility, 23 CFR 630 Subparts J & K (updated Sept 30, 2019) | <https://connect.ncdot.gov/projects/wztc/Documents/NCDOTFinalRuleImplementation.pdf> | 5 | 2026-10-27 |
| `part6.pdf` | MUTCD 11th Edition (December 2023), Part 6: Temporary Traffic Control | <https://mutcd.fhwa.dot.gov/pdfs/11th_Edition/part6.pdf> | 204 | 2026-10-27 |
| `bpguidebook.pdf` | Work Zone Operations Best Practices Guidebook, Third Edition (FHWA-HOP-13-012, 2013) | <https://ops.fhwa.dot.gov/wz/practices/best/documents/bpguidebook.pdf> | 293 | 2026-10-27 |
| `rule_guide.pdf` | Implementing the Rule on Work Zone Safety and Mobility (FHWA-HOP-05-065, September 2005) | <https://ops.fhwa.dot.gov/wz/rule_guide/rule_guide.pdf> | 103 | 2026-10-27 |
| `trans_mgmt_plans.pdf` | Developing and Implementing Transportation Management Plans for Work Zones (FHWA-HOP-05-066, December 2005) | <https://ops.fhwa.dot.gov/wz/resources/publications/trans_mgmt_plans/trans_mgmt_plans.pdf> | 131 | 2026-10-27 |
| `wzi_guide.pdf` | Work Zone Impacts Assessment: An Approach to Assess and Manage Work Zone Safety and Mobility Impacts of Road Projects (FHWA-HOP-05-068, August 2006) | <https://ops.fhwa.dot.gov/wz/resources/final_rule/wzi_guide/wzi_guide.pdf> | 184 | 2026-10-27 |
| `fhwahop14008.pdf` | Work Zone Intelligent Transportation Systems Implementation Guide (FHWA-HOP-14-008, January 2014) | <https://ops.fhwa.dot.gov/publications/fhwahop14008/fhwahop14008.pdf> | 80 | 2026-10-27 |
| `fhwahop12005.pdf` | Work Zone Road User Costs: Concepts and Applications (FHWA-HOP-12-005, December 2011) | <https://ops.fhwa.dot.gov/wz/resources/publications/fhwahop12005/fhwahop12005.pdf> | 208 | 2026-10-27 |
| `CFR-2024-title23-vol1-part630.pdf` | 23 CFR Part 630, Preconstruction Procedures, incl. Subpart J (Work Zone Safety and Mobility) and Subpart K (Temporary Traffic Control Devices) (revised April 1, 2024) | <https://www.govinfo.gov/content/pkg/CFR-2024-title23-vol1/pdf/CFR-2024-title23-vol1-part630.pdf> | 16 | 2026-10-27 |
| `04-20340.pdf` | Federal Register 69 FR 54562 (Sept 9, 2004): Work Zone Safety and Mobility Final Rule (23 CFR 630 Subpart J) | <https://www.govinfo.gov/content/pkg/FR-2004-09-09/pdf/04-20340.pdf> | 11 | 2026-10-27 |

## Utilities (`utilities`)

| File | Title | Source URL | Pages | Fetched |
|---|---|---|---|---|
| `20220713 NCDOT UAM Ver 2-0.pdf` | Utilities Accommodation Manual, Version 2.0 (July 2022) | <https://connect.ncdot.gov/municipalities/Utilities/UtilitiesDocuments/20220713%20NCDOT%20UAM%20Ver%202-0.pdf> | 311 | 2026-10-10 |
| `NCDOT Utility Cost Reimbursement Guidance_8-20-2026.pdf` | NCDOT Utility Cost Reimbursement Guidance (Aug 20, 2026) | <https://connect.ncdot.gov/municipalities/Utilities/UtilitiesDocuments/NCDOT%20Utility%20Cost%20Reimbursement%20Guidance_8-20-2026.pdf> | 5 | 2026-10-27 |
| `Encroachment_Requirements_Involving_Excessive_Height_Direct_Bury_Poles_5-26-2026.pdf` | NCDOT Encroachment Requirements Involving Excessive Height Direct Bury Poles (May 26, 2026) | <https://connect.ncdot.gov/municipalities/Utilities/UtilitiesDocuments/Encroachment_Requirements_Involving_Excessive_Height_Direct_Bury_Poles_5-26-2026.pdf> | 2 | 2026-10-27 |
| `18. Utility Plans.pdf` | NCDOT Roadway Design Manual Part II, Chapter 18: Utility Plans (Nov 2007) | <https://connect.ncdot.gov/projects/Roadway/Roadway%20Design%20Manual/18.%20Utility%20Plans.pdf> | 1 | 2026-10-27 |
| `09. Right of Way.pdf` | NCDOT Roadway Design Manual Part II, Chapter 9: Right of Way (Rev. 4, July 2007) | <https://connect.ncdot.gov/projects/Roadway/Roadway%20Design%20Manual/09.%20Right%20of%20Way.pdf> | 10 | 2026-10-27 |
| `UtilitiesCoordination-Encroachments-presentation-notes.pdf` | NCDOT Utilities Coordination and Encroachments Webinar, slides with speaker notes (Aug 2017) | <https://connect.ncdot.gov/projects/Project-Management/TrainingDocs/UtilitiesCoordination-Encroachments-presentation-notes.pdf> | 45 | 2026-10-27 |
| `DOT Encroachment Submissions User Manual - July 2023.pdf` | NCDOT Encroachment Submissions User Guide (July 2023) | <https://connect.ncdot.gov/municipalities/Utilities/UtilitiesDocuments/DOT%20Encroachment%20Submissions%20User%20Manual%20-%20July%202023.pdf> | 77 | 2026-10-27 |
| `Utility-Encroachment-Plan-Requirements.pdf` | NCDOT Standard Utility Encroachment Plan Requirements (July 2023) | <https://connect.ncdot.gov/municipalities/Utilities/EncroachmentForms/Utility-Encroachment-Plan-Requirements.pdf> | 2 | 2026-10-27 |
| `16-1-Two-Party-Utility-Primary-and-Secondary-Highways-Non-C-A.pdf` | NCDOT Right of Way Encroachment Agreement Form 16.1: Two-Party Utility, Primary and Secondary Highways (Non-Controlled Access) | <https://connect.ncdot.gov/municipalities/Utilities/EncroachmentForms/16-1-Two-Party-Utility-Primary-and-Secondary-Highways-Non-C-A.pdf> | 2 | 2026-10-27 |
| `if03014.pdf` | Program Guide: Utility Relocation and Accommodation on Federal-Aid Highway Projects, Sixth Edition (FHWA-IF-03-014, January 2003) | <https://www.fhwa.dot.gov/reports/utilguid/if03014.pdf> | 100 | 2026-10-27 |
| `utility_row.pdf` | Utility Accommodation within Federal-aid Rights-of-Way (FHWA Office of Infrastructure presentation, April 2018) | <https://www.fhwa.dot.gov/utilities/training/utility_row.pdf> | 15 | 2026-10-27 |
| `EDC-8_Factsheet_SUE.pdf` | Every Day Counts (EDC-8) Fact Sheet: Subsurface Utility Engineering (SUE) (2023) | <https://www.fhwa.dot.gov/innovation/everydaycounts/edc_8/pdf/EDC-8_Factsheet_SUE.pdf> | 2 | 2026-10-27 |
| `hif22002.pdf` | Tech Brief: Subsurface Utility Engineering Saves Time and Costs in Delaware (FHWA-HIF-22-002) | <https://www.fhwa.dot.gov/utilities/pdf/hif22002.pdf> | 6 | 2026-10-27 |
| `hif22040.pdf` | Case Study: UDOT Takes Active Role in Facilitating Broadband Deployment (FHWA-HIF-22-040) | <https://www.fhwa.dot.gov/utilities/pdf/hif22040.pdf> | 6 | 2026-10-27 |
| `010604.pdf` | Highway/Utility Guide (FHWA-SA-93-049, June 1993) | <https://www.fhwa.dot.gov/utilities/pdf/010604.pdf> | 316 | 2026-10-27 |
| `09utilcoordcert.pdf` | Federal-aid Essentials Companion Guide: Utility Coordination and Certification Requirements (August 2012) | <https://www.fhwa.dot.gov/federal-aidessentials/companionresources/09utilcoordcert.pdf> | 3 | 2026-10-27 |
| `fhwahop09021.pdf` | Rural Interstate Corridor Communications Study: Report to States (FHWA-HOP-09-021, February 2009) | <https://ops.fhwa.dot.gov/publications/fhwahop09021/fhwahop09021.pdf> | 140 | 2026-10-27 |
| `CFR-2024-title23-vol1-part645.pdf` | 23 CFR Part 645, Utilities (Subpart A Utility Relocations, Adjustments and Reimbursement; Subpart B Accommodation of Utilities) (revised April 1, 2024) | <https://www.govinfo.gov/content/pkg/CFR-2024-title23-vol1/pdf/CFR-2024-title23-vol1-part645.pdf> | 19 | 2026-10-27 |
| `CFR-2024-title23-vol1-part710.pdf` | 23 CFR Part 710, Right-of-Way and Real Estate (revised April 1, 2024) | <https://www.govinfo.gov/content/pkg/CFR-2024-title23-vol1/pdf/CFR-2024-title23-vol1-part710.pdf> | 23 | 2026-10-27 |

## Transportation Mobility and Safety (`tmsd`)

Chosen from the division's Traffic Safety Manuals page,
<https://connect.ncdot.gov/resources/safety/Pages/Traffic-Safety-Manuals.aspx>.

| File | Title | Source URL | Pages | Fetched |
|---|---|---|---|---|
| `TODS Manual - September 2024.pdf` | Tourist Oriented Directional Signs (TODS) Procedures Manual (September 2024) | <https://connect.ncdot.gov/resources/safety/Teppl/TEPPL%20All%20Documents%20Library/TODS%20Manual%20-%20September%202024.pdf> | 46 | 2026-10-27 |
| `Fatal Investigation Guidelines.pdf` | Guidelines for Investigation of Fatal Crashes (October 2019) | <https://connect.ncdot.gov/resources/safety/Teppl/TEPPL%20All%20Documents%20Library/Fatal%20Investigation%20Guidelines.pdf> | 5 | 2026-10-27 |
| `Policy on Access Manual.pdf` | NCDOT Policy on Street and Driveway Access to North Carolina Highways (July 2003) | <https://connect.ncdot.gov/resources/safety/Teppl/TEPPL%20All%20Documents%20Library/Policy%20on%20Access%20Manual.pdf> | 90 | 2026-10-27 |
| `Signal System Timing Philosophy Manual.pdf` | NCDOT Signal System Timing Philosophy Manual, Version 2.0 (Feb 1, 2017) | <https://connect.ncdot.gov/resources/safety/Teppl/TEPPL%20All%20Documents%20Library/Signal%20System%20Timing%20Philosophy%20Manual.pdf> | 61 | 2026-10-27 |
| `L18_TSLG_Guide.pdf` | NCDOT Traffic Services Legal Guide (revised June 20, 2023) | <https://connect.ncdot.gov/resources/safety/Teppl/TEPPL%20All%20Documents%20Library/L18_TSLG_Guide.pdf> | 706 | 2026-10-27 |
| `C34 - Manual 2012.pdf` | NCDOT DMV-349 Crash Report Instructional Manual (revised Aug 24, 2012) | <https://connect.ncdot.gov/resources/safety/Teppl/TEPPL%20All%20Documents%20Library/C34%20-%20Manual%202012.pdf> | 124 | 2026-10-27 |
| `03. Guardrail, Barriers and Attenuators.pdf` | NCDOT Roadway Design Manual Part I, Chapter 3: Guardrail, Barriers and Attenuators | <https://connect.ncdot.gov/projects/Roadway/Roadway%20Design%20Manual/03.%20Guardrail%2C%20Barriers%20and%20Attenuators.pdf> | 31 | 2026-10-27 |
| `09. At Grade Intersections.pdf` | NCDOT Roadway Design Manual Part I, Chapter 9: At Grade Intersections (Rev. 3, 2004) | <https://connect.ncdot.gov/projects/Roadway/Roadway%20Design%20Manual/09.%20At%20Grade%20Intersections.pdf> | 41 | 2026-10-27 |
| `bikeped_Ped_Policy.pdf` | NCDOT Pedestrian Policy Guidelines, Policy and Procedure Manual Chapter 28: Sidewalks (rev. Apr 16, 2001) | <https://connect.ncdot.gov/projects/BikePed/Documents/bikeped_Ped_Policy.pdf> | 15 | 2026-10-27 |
| `interim-design-safety-pilot-program.pdf` | NCDOT Interim Design Safety Pilot Project Final Report (September 2023) | <https://connect.ncdot.gov/projects/BikePed/Documents/interim-design-safety-pilot-program.pdf> | 58 | 2026-10-27 |
| `fhwa_hop_08_024.pdf` | Traffic Signal Timing Manual (FHWA-HOP-08-024, June 2008) | <https://ops.fhwa.dot.gov/publications/fhwahop08024/fhwa_hop_08_024.pdf> | 274 | 2026-10-27 |
| `Chapter2c.pdf` | MUTCD 11th Edition (December 2023), Chapter 2C: Warning Signs and Object Markers | <https://mutcd.fhwa.dot.gov/pdfs/11th_Edition/Chapter2c.pdf> | 58 | 2026-10-27 |
| `part3.pdf` | MUTCD 11th Edition (December 2023), Part 3: Markings | <https://mutcd.fhwa.dot.gov/pdfs/11th_Edition/part3.pdf> | 106 | 2026-10-27 |
| `01102.pdf` | Pedestrian Facilities Users Guide: Providing Safety and Mobility (FHWA-RD-01-102) | <https://www.fhwa.dot.gov/publications/research/safety/01102/01102.pdf> | 164 | 2026-10-27 |
| `04100.pdf` | Safety Effects of Marked Versus Unmarked Crosswalks at Uncontrolled Locations: Final Report and Recommended Guidelines (FHWA-HRT-04-100, September 2005) | <https://www.fhwa.dot.gov/publications/research/safety/04100/04100.pdf> | 114 | 2026-10-27 |
| `STEP-guide-improving-ped-safety.pdf` | Guide for Improving Pedestrian Safety at Uncontrolled Crossing Locations (FHWA STEP, July 2018, updated) | <https://www.fhwa.dot.gov/innovation/everydaycounts/edc_5/docs/STEP-guide-improving-ped-safety.pdf> | 41 | 2026-10-27 |
| `04091.pdf` | Signalized Intersections: Informational Guide (FHWA-HRT-04-091, August 2004) | <https://www.fhwa.dot.gov/publications/research/safety/04091/04091.pdf> | 372 | 2026-10-27 |
| `CFR-2024-title23-vol1-part924.pdf` | 23 CFR Part 924, Highway Safety Improvement Program (revised April 1, 2024) | <https://www.govinfo.gov/content/pkg/CFR-2024-title23-vol1/pdf/CFR-2024-title23-vol1-part924.pdf> | 6 | 2026-10-27 |
| `CFR-2024-title23-vol1-part655.pdf` | 23 CFR Part 655, Traffic Operations (MUTCD adoption) (revised April 1, 2024) | <https://www.govinfo.gov/content/pkg/CFR-2024-title23-vol1/pdf/CFR-2024-title23-vol1-part655.pdf> | 8 | 2026-10-27 |
