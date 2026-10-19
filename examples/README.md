# Synthetic examples

`demo-report.html` is generated from explicitly fictional data. It illustrates the offline dashboard and does not contain real candidate information or actual doctoral offers/submissions.

Generate a complete separate example with editable documents, assessment, verified local packet, recorded synthetic submission, tracker and calendar:

```bash
python3 tools/demo.py --workspace /tmp/phd-demo --out /tmp/phd-demo.html
```

The workspace must be a new directory. Add `--pdf` to exercise an installed compiler; compilation does not attest visual review. Your personal `workspace/` remains untouched. The synthetic example uses comparative literature to demonstrate that publications, a lab, coding skills and a STEM research design are not universal requirements.

`modes-report.html` demonstrates two additional, explicitly fictional complete application journeys: a research internship and a winter school. Generate it in a new workspace with `python3 tools/modes_demo.py --workspace /tmp/research-roost-modes-demo --out /tmp/research-roost-modes-demo.html`. No real submission occurs.
