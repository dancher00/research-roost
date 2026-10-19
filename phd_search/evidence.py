from __future__ import annotations

import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

from .core import (
    Error,
    atomic_write,
    canonical_url,
    contained,
    digest,
    json_text,
    now,
    read_json,
)
from .extract import extract
from .network import MAX_BYTES, Client, Response
from .store import Store


class _AccessPage(HTMLParser):
    """Recognise access forms/widgets while keeping navigation outside posting content."""

    _void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    _login_route = re.compile(r"(?:^|[/#?=&_\s-])(?:log[-_]?in|sign[-_]?in|sso|oauth2?|authenticate)(?:[/#?=&_\s-]|$)", re.I)
    _challenge_route = re.compile(r"/cdn-cgi/challenge-platform/|challenges\.cloudflare\.com/|(?:^|/)hcaptcha\.com/|/recaptcha/(?:api|enterprise)\.js", re.I)

    def __init__(self, markup: str):
        super().__init__(convert_charrefs=True)
        self.frames = []
        self.forms = []
        self.outside = []
        self.article = []
        self.titles = []
        self.headings = []
        self.challenge = False
        self.feed(markup)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        parent = self.frames[-1] if self.frames else {}
        ignored = (parent.get("ignored", False) or tag in {"head", "script", "style", "noscript", "template", "svg"}
                   or "hidden" in attrs or attrs.get("aria-hidden") == "true"
                   or bool(re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", attrs.get("style") or "", re.I)))
        chrome = parent.get("chrome", False) or tag in {"header", "footer", "nav", "aside"} or attrs.get("role") in {"navigation", "banner", "contentinfo"}
        form = parent.get("form")
        if tag == "form":
            markers = " ".join(attrs.get(key) or "" for key in ("action", "id", "class"))
            form = {"password": False, "identity": False, "login_route": bool(self._login_route.search(markers)), "chrome": chrome, "active": not ignored, "submits": []}
            self.forms.append(form)
        submit = parent.get("submit")
        if form is not None and (tag == "button" and (attrs.get("type") or "submit").casefold() == "submit"
                                 or tag == "input" and (attrs.get("type") or "").casefold() == "submit"):
            submit = {"parts": [attrs.get("value") or ""]}
            form["submits"].append(submit)
        if tag == "input" and form is not None and not ignored:
            kind = (attrs.get("type") or "text").casefold()
            autocomplete = (attrs.get("autocomplete") or "").casefold()
            if kind == "password" or autocomplete in {"current-password", "new-password", "one-time-code"}:
                form["password"] = True
            if kind == "email" or autocomplete == "username" or (attrs.get("name") or "").casefold() in {"username", "email", "login"}:
                form["identity"] = True
        if tag in {"script", "iframe", "form"}:
            route = attrs.get("src") or attrs.get("action") or ""
            if self._challenge_route.search(route) or tag == "form" and (attrs.get("id") or "").casefold() in {"challenge-form", "cf-challenge-form"}:
                self.challenge = True
        widgets = set((attrs.get("class") or "").casefold().split())
        if widgets & {"g-recaptcha", "h-captcha", "cf-turnstile"} and attrs.get("data-sitekey"):
            self.challenge = True
        frame = {"tag": tag, "ignored": ignored, "chrome": chrome, "form": form,
                 "article": parent.get("article", False) or tag in {"main", "article"} or attrs.get("role") == "main", "submit": submit}
        if tag not in self._void:
            self.frames.append(frame)

    def handle_endtag(self, tag):
        for index in range(len(self.frames) - 1, -1, -1):
            if self.frames[index]["tag"] == tag:
                del self.frames[index:]
                break

    def handle_data(self, data):
        frame = self.frames[-1] if self.frames else {}
        if frame.get("tag") == "title":
            self.titles.append(data)
        if frame.get("tag") == "h1" and not frame.get("ignored") and not frame.get("chrome"):
            self.headings.append(data)
        if frame.get("submit") is not None and not frame.get("ignored"):
            frame["submit"]["parts"].append(data)
        if frame.get("tag") == "script" and "window._cf_chl_opt" in data:
            self.challenge = True
        if not frame.get("ignored") and not frame.get("chrome") and frame.get("form") is None:
            self.outside.append(data)
            if frame.get("article"):
                self.article.append(data)


def check_html_access(markup: str, data: dict | None = None, headers: dict | None = None) -> None:
    """Apply the same access-shell check to posting and HTML-discovery boundaries."""
    data = data or {}
    headers = headers or {}
    page = _AccessPage(markup)
    outside = " ".join(" ".join(page.outside).split())
    article = " ".join(" ".join(page.article).split())
    description = " ".join(data.get("description", "").split())
    visible_posting = (data.get("extraction", {}).get("method") == "jsonld" and len(description) >= 40
                       and data.get("title", "").strip().casefold() in outside.casefold() and description.casefold() in outside.casefold())
    substantial = (sum(char.isalnum() for char in outside) >= 220 or len(outside.split()) >= 40
                   or sum(char.isalnum() for char in article) >= 120 or visible_posting)
    auth_forms = [form for form in page.forms if form["active"] and (form["password"] or form["identity"] and form["login_route"])]
    title = " ".join(" ".join(page.titles).split())
    heading = " ".join(" ".join(page.headings).split())
    # A document named after its central authentication submit action is still
    # an account shell when its help/privacy instructions are arbitrarily long.
    action_named_shell = (title and (heading.casefold() == title.casefold() or heading.casefold().startswith(title.casefold() + " "))
                          and any(not form["chrome"] and title.casefold() in {
                              " ".join(" ".join(button["parts"]).split()).casefold() for button in form["submits"]
                          } for form in auth_forms))
    # A small sign-in widget in navigation does not hide the readable posting.
    ancillary_only = auth_forms and all(form["chrome"] for form in auth_forms) and sum(char.isalnum() for char in outside) >= 40
    if (action_named_shell and not visible_posting) or (auth_forms and not substantial and not ancillary_only):
        raise Error("Posting unavailable: received an authentication form instead of readable posting content")
    lowered = {key.casefold(): value.casefold() for key, value in headers.items() if isinstance(value, str)}
    browser_shell = (re.match(r"^(?:checking|verifying) your browser\b", title, re.I)
                     and re.match(r"^verify (?:that )?you are (?:a )?human\b", heading, re.I)
                     and re.search(r"\benable JavaScript and cookies to (?:continue|proceed)\b", outside, re.I))
    challenged = (page.challenge or lowered.get("cf-mitigated") == "challenge"
                  or lowered.get("x-amzn-waf-action") in {"challenge", "captcha"} or browser_shell)
    if challenged and not substantial:
        raise Error("Posting unavailable: received a browser/CAPTCHA challenge instead of readable posting content")


def verify_external(root: Path, item: dict) -> Path:
    if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k].strip() for k in ("file", "sha256", "quote", "url")):
        raise Error("External evidence requires file, sha256, quote and original url")
    canonical_url(item["url"])
    path = contained(root, item["file"])
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise Error("External evidence is missing or exceeds the text evidence size limit")
    body = path.read_bytes()
    if digest(body) != item["sha256"] or item["quote"] not in body.decode("utf-8", "replace"):
        raise Error("External evidence changed or does not contain the quoted text")
    return path


def pdf_text(body: bytes, root: Path) -> str:
    path = root / "cache" / (digest(body) + ".pdf")
    atomic_write(path, body)
    try:
        from pypdf import PdfReader
    except ImportError:
        PdfReader = None
    if PdfReader:
        try:
            text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
            if text.strip():
                return text
        except Exception:
            pass
    if shutil.which("pdftotext"):
        try:
            result = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, timeout=40, check=True)
            text = result.stdout.decode("utf-8", "replace")
            if text.strip():
                return text
        except (subprocess.SubprocessError, OSError) as exc:
            raise Error(f"PDF extraction failed: {exc}") from exc
    raise Error("No usable PDF text layer. Install the optional pypdf extra or use pdftotext; scanned documents need external OCR and human review")


def ingest_response(store: Store, response: Response, *, source: str | None = None, mode: str | None = None,
                    edition: str | None = None, session: str | None = None) -> dict:
    body = response.body
    if len(body) > MAX_BYTES:
        raise Error("Input exceeds the evidence size limit")
    if body.startswith(b"%PDF") or "application/pdf" in response.content_type:
        text = pdf_text(body, store.root)
        mode = "text"
    else:
        text = response.text
        mode = mode or ("html" if "html" in response.content_type or text.lstrip().startswith(("<!DOCTYPE", "<!doctype", "<html")) else "text")
    data, cleaned, findings = extract(text, response.url, mode=mode)
    if mode == "html":
        check_html_access(text, data, response.headers)
    data["source"] = source or "direct"
    sha = digest(body)
    raw_relative = f"evidence/{sha[:2]}/{sha}.raw"
    text_relative = f"evidence/{sha[:2]}/{sha}-{digest(cleaned)[:16]}.txt"
    atomic_write(store.root / raw_relative, body)
    atomic_write(store.root / text_relative, cleaned)
    snapshot = {"sha256": sha, "raw_path": raw_relative, "text_path": text_relative,
                "url": response.url, "fetched_at": response.fetched_at,
                "metadata": {"content_type": response.content_type, "source": source or "direct", "cached": response.cached,
                             "requested_url": response.requested_url or response.url,
                             "text_sha256": digest(cleaned), "integrity": findings, "extraction_mode": mode}}
    atomic_write(store.root / f"evidence/{sha[:2]}/{sha}-{digest(json_text(snapshot))[:16]}.metadata.json", json_text(snapshot))
    return store.ingest(response.url, data, snapshot, edition=edition, session=session)


def ingest_url(store: Store, client: Client, url: str, *, source: str | None = None, refresh: bool = False,
               edition: str | None = None, session: str | None = None) -> dict:
    return ingest_response(store, client.get(url, refresh=refresh), source=source, edition=edition, session=session)


def ingest_file(store: Store, path: Path, url: str, *, mode: str | None = None, source: str = "manual-import",
                edition: str | None = None, session: str | None = None) -> dict:
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise Error(f"Input missing or larger than {MAX_BYTES} bytes: {path}")
    content_type = "text/html" if mode == "html" or path.suffix.lower() in {".html", ".htm"} else "text/plain"
    if path.suffix.lower() == ".pdf":
        content_type = "application/pdf"
    return ingest_response(store, Response(url, path.read_bytes(), content_type, {}, now()), source=source, mode=mode,
                           edition=edition, session=session)


def register_document(root: Path, path: Path, category: str) -> dict:
    allowed = {"cv", "transcripts", "diplomas", "publications", "portfolio", "references", "language-tests", "other"}
    if category not in allowed:
        raise Error("Document category must be one of: " + ", ".join(sorted(allowed)))
    if not path.is_file() or path.stat().st_size > 30 * 1024 * 1024:
        raise Error("Document missing or larger than 30 MiB")
    from .core import slug
    body = path.read_bytes()
    sha = digest(body)
    version = f"documents/{category}/{sha}-{slug(path.name)}"
    directory = root / version
    relative = version + "/original" + path.suffix.lower()
    metadata_path = directory / "metadata.json"
    try:
        directory.mkdir(parents=True)
    except FileExistsError:
        if not directory.is_dir() or not metadata_path.is_file():
            raise Error("Document version already exists but is incomplete; inspect it before importing again") from None
        metadata = read_json(metadata_path)
        if (not isinstance(metadata, dict) or metadata.get("file") != relative or metadata.get("sha256") != sha
                or not (root / relative).is_file() or digest((root / relative).read_bytes()) != sha):
            raise Error("Preserved document version changed; existing files were not overwritten")
        if metadata.get("extraction") == "available":
            text_file = version + "/extracted.txt"
            if (metadata.get("text_file") != text_file or not (root / text_file).is_file()
                    or digest((root / text_file).read_bytes()) != metadata.get("text_sha256")):
                raise Error("Preserved document extraction changed; existing files were not overwritten")
        return metadata
    metadata = {"file": relative, "original_name": path.name, "category": category, "sha256": sha, "imported_at": now()}
    try:
        atomic_write(root / relative, body)
        try:
            if body.startswith(b"%PDF"):
                if len(body) > MAX_BYTES:
                    raise Error("PDF too large for bounded automatic extraction")
                text = pdf_text(body, root)
            elif path.suffix.lower() in {".txt", ".md", ".tex", ".csv", ".json"}:
                text = body.decode("utf-8", "replace")
            elif path.suffix.lower() in {".html", ".htm"}:
                text = extract(body.decode("utf-8", "replace"), "https://document.invalid/", mode="html")[1]
            else:
                raise Error("Format preserved; text extraction is not available for this document type")
            from .vendor.posting_guard import guard
            text, findings = guard(text, "text")
            text_file = version + "/extracted.txt"
            atomic_write(root / text_file, text)
            metadata.update(text_file=text_file, text_sha256=digest(text), integrity=findings, extraction="available")
        except Error as exc:
            metadata.update(extraction="unavailable", reason=str(exc))
        atomic_write(metadata_path, json_text(metadata))
    except BaseException:
        shutil.rmtree(directory)
        raise
    return metadata
