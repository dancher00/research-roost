from __future__ import annotations

import html
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .applications import get_application
from .core import Error, atomic_write, contained, digest, json_text, now, read_json
from .store import Store

LATEX = r"""\documentclass[11pt,a4paper]{article}
\usepackage[margin=24mm]{geometry}
\usepackage{fontspec}
\IfFontExistsTF{Noto Serif}{\setmainfont{Noto Serif}}{\IfFontExistsTF{DejaVu Serif}{\setmainfont{DejaVu Serif}}{\setmainfont{Latin Modern Roman}}}
\usepackage{enumitem}
\usepackage[hidelinks]{hyperref}
\setlength{\parindent}{0pt}
\setlength{\parskip}{6pt}
\setlist{nosep,leftmargin=*}
\begin{document}
{{BODY}}
\end{document}
"""


def tex_escape(text: str) -> str:
    mapping = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return "".join(mapping.get(c, c) for c in text)


def markdown_tex(markdown: str) -> str:
    out = []
    in_list = False
    for line in markdown.splitlines():
        if in_list and not re.match(r"\s*[-*] ", line):
            out.append(r"\end{itemize}")
            in_list = False
        text = tex_escape(re.sub(r"\*\*(.+?)\*\*", r"\1", line))
        if line.startswith("# "):
            out.append(r"{\Large\bfseries " + tex_escape(line[2:]) + r"}\par")
        elif line.startswith("## "):
            out.append(r"\section*{" + tex_escape(line[3:]) + "}")
        elif line.startswith("### "):
            out.append(r"\subsection*{" + tex_escape(line[4:]) + "}")
        elif re.match(r"\s*[-*] ", line):
            if not in_list:
                out.append(r"\begin{itemize}")
                in_list = True
            out.append(r"\item " + tex_escape(re.sub(r"^\s*[-*] ", "", line)))
        else:
            out.append(text)
    if in_list:
        out.append(r"\end{itemize}")
    return "\n".join(out)


def markdown_html(markdown: str) -> str:
    lines = []
    for line in markdown.splitlines():
        escaped = html.escape(line)
        if line.startswith("### "):
            lines.append("<h3>" + html.escape(line[4:]) + "</h3>")
        elif line.startswith("## "):
            lines.append("<h2>" + html.escape(line[3:]) + "</h2>")
        elif line.startswith("# "):
            lines.append("<h1>" + html.escape(line[2:]) + "</h1>")
        elif line.strip():
            lines.append("<p>" + escaped + "</p>")
    return "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>Application document</title><style>body{font:11pt/1.55 Georgia,serif;max-width:170mm;margin:24mm auto;padding:0 12mm;color:#172033}h1{font-size:23pt}h2{font-size:14pt;margin-top:1.8em}p{white-space:pre-wrap}@page{size:A4;margin:24mm}@media print{body{margin:0;padding:0;max-width:none}h1,h2,h3{break-after:avoid}}</style></head><body>" + "\n".join(lines) + "</body></html>"


def compile_tex(path: Path, engine: str, *, timeout: int = 60) -> dict:
    if engine not in {"xelatex", "lualatex", "tectonic"}:
        raise Error("Supported engines: xelatex, lualatex, tectonic")
    executable = shutil.which(engine)
    if not executable:
        return {"state": "unavailable", "reason": f"{engine} is not on PATH; editable source and print HTML are still available"}
    if engine == "tectonic":
        command = [executable, "--untrusted", "--outdir", str(path.parent), str(path)]
    else:
        command = [executable, "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "-output-directory", str(path.parent), str(path)]
    try:
        result = subprocess.run(command, cwd=path.parent, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"state": "fail", "reason": f"Compilation exceeded {timeout}s"}
    except OSError as exc:
        return {"state": "fail", "reason": str(exc)}
    atomic_write(path.with_suffix(".compile.log"), (result.stdout + b"\n" + result.stderr)[-100000:])
    if result.returncode != 0 or not path.with_suffix(".pdf").is_file():
        return {"state": "fail", "reason": "Compilation failed; inspect the compile log", "exit_code": result.returncode}
    return {"state": "pass", "pdf": str(path.with_suffix(".pdf")), "engine": engine}


def render_application(store: Store, identifier: str, *, compile_pdf: bool = False, engine: str = "auto", template: str | None = None) -> dict:
    app = get_application(store, identifier)
    directory = store.root / app["data"]["directory"]
    rendered = directory / "rendered"
    rendered.mkdir(exist_ok=True)
    wrapper = LATEX
    if engine == "auto":
        engine = next((name for name in ("xelatex", "lualatex", "tectonic") if shutil.which(name)), "xelatex")
    if template:
        templates = read_json(store.root / "templates.json")
        selected = next((x for x in templates["templates"] if x["id"] == template), None)
        if not selected:
            raise Error("Unknown template")
        wrapper = contained(store.root, selected["source"]).read_text()
        if digest(wrapper) != selected["source_sha256"]:
            raise Error("Registered template changed; register and test the new version")
        engine = selected["engine"]
    results = []
    for filename in app["data"]["documents"]:
        path = contained(directory, filename)
        if not path.is_file():
            raise Error(f"Missing source document {filename}")
        markdown = path.read_text()
        tex = rendered / (path.stem + ".tex")
        atomic_write(tex, wrapper.replace("{{BODY}}", markdown_tex(markdown)))
        atomic_write(rendered / (path.stem + ".html"), markdown_html(markdown))
        item = {"document": filename, "tex": str(tex), "html": str(rendered / (path.stem + ".html")), "source_sha256": digest(markdown)}
        if compile_pdf:
            item["compilation"] = compile_tex(tex, engine)
            if item["compilation"]["state"] == "pass":
                pdf = tex.with_suffix(".pdf")
                manifest = {"source_sha256": digest(markdown), "tex_sha256": digest(tex.read_bytes()), "pdf_sha256": digest(pdf.read_bytes()), "engine": engine, "compiled_at": now()}
                atomic_write(tex.with_suffix(".build.json"), json_text(manifest))
        results.append(item)
    return {"application_id": app["id"], "documents": results}


def register_template(root: Path, identifier: str, source: Path, engine: str) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", identifier):
        raise Error("Template id must be a lowercase slug")
    if not source.is_file() or source.stat().st_size > 1024 * 1024:
        raise Error("Template missing or larger than 1 MiB")
    text = source.read_text()
    if text.count("{{BODY}}") != 1:
        raise Error("LaTeX template must contain exactly one {{BODY}} placeholder")
    templates = read_json(root / "templates.json")
    if any(t["id"] == identifier for t in templates["templates"]):
        raise Error("Template id already exists; choose a versioned id")
    with tempfile.TemporaryDirectory(prefix="phd-template-") as temporary:
        test = Path(temporary) / "test.tex"
        test.write_text(text.replace("{{BODY}}", markdown_tex("# Template test\n\nResearch & evidence: 100% Unicode — α, é.\n\n- A supported claim\n- Another claim")))
        result = compile_tex(test, engine)
        if result["state"] != "pass":
            raise Error("Template was not registered: mandatory test compile " + result["state"] + ": " + result.get("reason", ""))
    relative = f"templates/{identifier}.tex"
    atomic_write(root / relative, text)
    entry = {"id": identifier, "source": relative, "source_sha256": digest(text), "engine": engine, "test_compiled_at": now()}
    templates["templates"].append(entry)
    atomic_write(root / "templates.json", json_text(templates))
    return entry
