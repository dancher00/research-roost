# Research and training fit rubrics

ResearchRoost uses separate, versioned prioritisation rubrics for PhD opportunities, research internships and schools. These are not admissions probabilities, expert certifications or prestige metrics. Use disciplinary reasoning and the actual project/programme requirements. The same user-confirmed profile and explicit evidence must underlie comparable assessments. See [opportunity families](opportunities.md).

The assessment packet binds `rubric: {"id": "phd"|"internship"|"school", "version": 1, "family": ...}` to the current source/profile context. Complete the dimensions in that packet; do not copy a PhD packet onto a school. Existing packets without rubric metadata are compatible only with the legacy PhD rubric. Changing an opportunity's family invalidates a previous assessment.

## PhD rubric: `phd`, version 1

| Dimension | Weight | Question |
|---|---:|---|
| research_fit | 30 | Do the candidate's questions and evidenced trajectory connect to the advertised research agenda? |
| methods | 20 | Is the candidate prepared for the actual methods/materials/practice, and are the training gaps realistic? |
| supervisor_fit | 15 | Is there evidenced intellectual/supervisory fit, with availability/mentoring facts separated from unknowns? |
| preparedness | 15 | Do demonstrated research/practice contributions and formal preparation support this specific doctoral route? |
| funding | 15 | Are coverage, duration, candidate eligibility and financial conditions suitable for confirmed preferences? |
| environment | 5 | Do verified training/resources/access/programme conditions support the proposed work and constraints? |

## Research internship rubric: `internship`, version 1

| Dimension | Weight | Question |
|---|---:|---|
| project_fit | 30 | Does the actual placement question or project connect to the candidate's evidenced trajectory and intended contribution? |
| methods | 20 | Is preparation appropriate for the advertised methods/materials/practice and feasible training during the placement? |
| mentor_fit | 15 | Is there evidence of a suitable mentor/project team and a relevant working agenda, with availability kept distinct from assumptions? |
| preparedness | 15 | Do demonstrated contributions and actual prerequisites support work at this placement's level? |
| funding | 15 | Are pay/support, duration and uncovered costs suitable for confirmed needs, with conditional awards and permissions explicit? |
| environment | 5 | Do sourced resources, access, format and working conditions support this time-limited project? |

An internship may be archival, curatorial, clinical, field-based, theoretical, artistic or computational. A software job is not research merely because a PhD student can apply. A potential publication is not a guaranteed internship outcome. Degree enrollment, return to study, home approval and work authorization are eligibility checks, not points awarded for a promising project.

## School rubric: `school`, version 1

Summer, winter, research, training and field schools and short courses share this training rubric. The season does not change the scoring contract.

| Dimension | Weight | Question |
|---|---:|---|
| learning_fit | 30 | Does the actual syllabus advance a specific, evidenced research question, method or learning goal? |
| prerequisites | 20 | Does candidate evidence meet the stated background, language, technical or practice prerequisites at the right level? |
| programme_fit | 15 | Do sourced content, instructors, exercises and expected outputs provide appropriate depth and a realistic subsequent use? |
| funding | 20 | Are registration, living, accommodation and travel coverage and candidate eligibility suitable for confirmed needs? |
| practical_fit | 15 | Are event dates, duration, format, location, access and workload compatible with confirmed availability and constraints? |

A school is not assessed for doctoral supervision, a three-year research proposal or a promised research job. Instructors' works can support a content assessment but do not prove they are recruiting students. Unknown availability or event access stays unknown. A waived registration fee does not establish a fully covered trip.

## Shared evidence and scoring rules

Each score is null or 0–5:

| Score | Evidence-bounded anchor |
|---:|---|
| null | Evidence is insufficient; do not infer a neutral, average or zero score. |
| 0 | Directly evidenced incompatibility or absence of a required contribution; explain precisely. |
| 1 | Weak connection and substantial evidenced gaps. |
| 2 | Some connection/transferability, but major preparation or scope gaps. |
| 3 | Credible fit with specific, feasible development needs. |
| 4 | Strong direct fit supported by concrete examples, with limited material gaps. |
| 5 | Particularly clear, detailed fit across this dimension's relevant requirements; no unsupported superlatives. |

For each scored dimension write reasoning and exact source excerpts. Candidate-specific fit/preparation dimensions also require relevant profile JSON pointers; follow the packet validator. A 5 does not require a publication if the opportunity does not require one; methods may be theoretical, interpretive, quantitative, qualitative, experimental, clinical, archival, artistic or practice-based. Supervisor/mentor fit is not inferred from institution ranking. Programme content and environment are not judged from marketing copy alone.

Eligibility gates run separately and can veto or flag an opportunity regardless of score. They cover only actual sourced requirements and configured preferences. `requirements.reviewed` is required before an eligibility pass can be considered complete within the recorded scope. Degree equivalence, nationality/fee categories, mobility, ambiguous language rules, enrollment through an internship's end, return to study, home approval and work permission remain explicit questions when supporting evidence is missing. Actual named deadline roles must stay distinct; a later registration cutoff cannot rescue an expired required application cutoff.

Weighted subtotal = sum(score / 5 × weight) over assessed dimensions. Coverage = sum of their weights. Unknown dimensions contribute an interval [0, weight]; the overall interval is [subtotal, subtotal + missing weight]. Return a point score only when all dimensions are assessed. For example, only research_fit=4 gives coverage 30%, interval 24–94 and score null. This interval describes missing rubric evidence, not a confidence/credible interval.

Ranking keeps family/rubric `comparison_group` values distinct and groups confirmed pass/unknown/fail eligibility within comparable results, then prioritises assessed coverage and known subtotal. A school score of 85 cannot be interpreted as superior to a PhD score of 80. Use family-filtered ranking and explain cross-family goal/timing trade-offs in prose. Partial intervals may overlap widely: explain why an interesting but unknown-funded option still needs research. Include failed opportunities on request and preserve the reason rather than hiding them.

Reassess when profile, posting or sourced annotations change. Time-sensitive availability, grant terms and deadlines may require a fresh retrieval even when bytes were last seen unchanged. Record strengths, gaps, questions and a concrete next step. Do not calibrate admission probabilities from a handful of selected outcomes.
