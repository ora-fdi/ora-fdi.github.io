#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

DOMAIN_DIR = {"ERP": "erp_topic_refs", "HCM": "hr_topic_refs", "SCM": "scm_topic_refs"}
ZIP_RE = re.compile(r"^(?P<release>\d{2}R\d)_Fusion_(?P<domain>ERP|HCM|SCM)_Analytics_Tables\.zip$", re.I)
HTML_RE = re.compile(r"^(?P<release>\d{2}R\d)_Fusion_(?P<domain>ERP|HCM|SCM)_Analytics_Tables\.html$", re.I)


def fail(msg: str) -> None:
    raise SystemExit(f"ERROR: {msg}")


def safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    dest_resolved = dest.resolve()
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        if target != dest_resolved and dest_resolved not in target.parents:
            fail(f"Unsafe path in ZIP: {member.filename}")
    zf.extractall(dest)


def remove_dead_commonltr(text: str) -> str:
    return re.sub(
        r'\s*<link\s+rel="stylesheet"\s+type="text/css"\s+href="(?:\.\./\.\./)?commonltr\.css"\s*/>\s*',
        "\n",
        text,
        flags=re.I,
    )


def process_zip(repo: Path, zip_path: Path) -> tuple[str, str, str]:
    m = ZIP_RE.match(zip_path.name)
    if not m:
        fail(f"Unexpected ZIP filename: {zip_path.name}")
    release = m.group("release").upper()
    domain = m.group("domain").upper()
    domain_dir = DOMAIN_DIR[domain]

    with tempfile.TemporaryDirectory() as td:
        temp = Path(td)
        with zipfile.ZipFile(zip_path) as zf:
            safe_extract(zf, temp)

        landing = temp / f"{release}_Fusion_{domain}_Analytics_Tables.html"
        topic_refs = temp / "topic_refs"
        book_css = temp / "book.css"
        if not landing.is_file():
            fail(f"{zip_path.name}: missing expected landing page {landing.name}")
        if not topic_refs.is_dir():
            fail(f"{zip_path.name}: missing topic_refs directory")
        if not book_css.is_file():
            fail(f"{zip_path.name}: missing book.css")

        topic_files = list(topic_refs.glob("*.html"))
        if not topic_files:
            fail(f"{zip_path.name}: topic_refs contains no HTML files")

        landing_text = landing.read_text(encoding="utf-8-sig")
        landing_text = remove_dead_commonltr(landing_text)
        landing_text = landing_text.replace('href="topic_refs/', f'href="{domain_dir}/')

        # Remove previous active landing page(s) for this domain.
        for old in repo.glob(f"*_Fusion_{domain}_Analytics_Tables.html"):
            old.unlink()

        target_dir = repo / domain_dir
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True)

        for src in topic_files:
            text = remove_dead_commonltr(src.read_text(encoding="utf-8-sig"))
            (target_dir / src.name).write_text(text, encoding="utf-8", newline="\n")

        (repo / landing.name).write_text(landing_text, encoding="utf-8", newline="\n")
        shutil.copy2(book_css, repo / "book.css")

    return domain, release, landing.name


def update_readme(repo: Path, updates: dict[str, tuple[str, str]]) -> None:
    readme = repo / "README.md"
    if not readme.is_file():
        fail("README.md not found")
    text = readme.read_text(encoding="utf-8")
    labels = {"ERP": "ERP Tables", "HCM": "HCM Tables", "SCM": "SCM Tables"}
    for domain, (_, html_name) in updates.items():
        pattern = rf"(?m)^- \[{re.escape(labels[domain])}\]\([^\n]+\)$"
        replacement = f"- [{labels[domain]}](/{html_name})"
        text, count = re.subn(pattern, replacement, text)
        if count != 1:
            fail(f"Could not uniquely update README link for {domain}; matched {count} lines")
    readme.write_text(text, encoding="utf-8", newline="\n")


def validate(repo: Path, updates: dict[str, tuple[str, str]]) -> None:
    errors: list[str] = []
    for domain, (_, html_name) in updates.items():
        domain_dir = DOMAIN_DIR[domain]
        landing = repo / html_name
        text = landing.read_text(encoding="utf-8")
        if "commonltr.css" in text:
            errors.append(f"{html_name}: still references missing commonltr.css")
        refs = re.findall(r'href="([^"#?]+\.html)"', text, flags=re.I)
        for ref in refs:
            target = (repo / ref).resolve()
            if not target.is_file():
                errors.append(f"{html_name}: broken link {ref}")
        for topic in (repo / domain_dir).glob("*.html"):
            t = topic.read_text(encoding="utf-8")
            if "commonltr.css" in t:
                errors.append(f"{topic.relative_to(repo)}: still references missing commonltr.css")
            if 'href="../book.css"' not in t:
                errors.append(f"{topic.relative_to(repo)}: missing expected ../book.css reference")
    if errors:
        fail("Validation failed:\n" + "\n".join(errors[:100]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish Oracle FDI analytics table ZIPs into this GitHub Pages repo.")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--incoming", type=Path, default=Path("incoming"))
    parser.add_argument("--delete-zips", action="store_true")
    args = parser.parse_args()

    repo = args.repo.resolve()
    incoming = args.incoming if args.incoming.is_absolute() else repo / args.incoming
    zips = sorted(incoming.glob("*.zip"))
    if not zips:
        fail(f"No ZIP files found in {incoming}")

    updates: dict[str, tuple[str, str]] = {}
    for z in zips:
        domain, release, html_name = process_zip(repo, z)
        if domain in updates:
            fail(f"More than one {domain} ZIP supplied in the same run")
        updates[domain] = (release, html_name)
        print(f"Prepared {domain} {release}: {html_name}")

    update_readme(repo, updates)
    validate(repo, updates)

    if args.delete_zips:
        for z in zips:
            z.unlink()

    summary = ", ".join(f"{d} {r}" for d, (r, _) in sorted(updates.items()))
    print(f"Catalog update complete: {summary}")


if __name__ == "__main__":
    main()
