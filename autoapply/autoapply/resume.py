"""Parse a resume (PDF/DOCX/TXT) into plain text and extract skills."""
from __future__ import annotations

import re
from pathlib import Path

# A pragmatic starter skill list (editable). Matches case-insensitively
# as whole words.
SKILLS = [
    "python", "typescript", "javascript", "react", "nextjs", "node",
    "fastapi", "flask", "django", "postgres", "postgresql", "mysql",
    "sqlite", "mongodb", "redis", "docker", "kubernetes", "k8s", "aws",
    "gcp", "azure", "git", "linux", "ci/cd", "selenium", "playwright",
    "scraping", "llm", "gpt", "openai", "langchain", "tensorflow",
    "pytorch", "machine learning", "ml", "ai", "nlp", "html", "css",
    "tailwind", "rest api", "graphql", "pandas", "numpy",
    "microservices", "celery", "websockets", "oauth", "jwt", "pytest",
    "java", "go", "golang", "c++", "rust", "sql", "excel", "figma",
]


def parse_resume(path: str | Path | None) -> str:
    """Extract plain text from a PDF/DOCX/TXT resume file."""
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        print(f"[resume] file not found: {p}")
        return ""
    suffix = p.suffix.lower()
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(p))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        if suffix == ".docx":
            import docx
            doc = docx.Document(str(p))
            return "\n".join(par.text for par in doc.paragraphs)
        if suffix in (".txt", ".md"):
            return p.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        print(f"[resume] parse error: {exc}")
        return ""
    print(f"[resume] unsupported format: {suffix} (use PDF/DOCX/TXT)")
    return ""


def extract_skills(text: str, skill_list: list[str] | None = None) -> list[str]:
    """Return skills from the resume text that appear in the list."""
    skills = skill_list or SKILLS
    lowered = text.lower()
    found = []
    for skill in skills:
        if re.search(rf"\b{re.escape(skill)}\b", lowered):
            found.append(skill)
    return found


def extract_email(text: str) -> str:
    m = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
    return m.group(0) if m else ""
