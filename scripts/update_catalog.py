#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

DOMAIN_DIR = {
    "ERP": "erp_topic_refs",
    "HCM": "hr_topic_refs",
    "SCM": "scm_topic_refs",
}

ZIP_RE = re.compile(
    r"^(?P<release>\d{2}R\d)_Fusion_(?P<domain>ERP|HCM|SCM)_Analytics_Tables\.zip$",
    re.I,
)

DOC_INFO = {
    "HCM": {
        "guide": "fahia",
        "label": "HR (HCM) Data",
    },
    "ERP": {
        "guide": "faiae",
        "label": "Finance (ERP) Data",
    },
    "SCM": {
        "guide": "fascm",
        "label": "Procurement (SCM) Data",
    },
}


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
        r'\s*<link\s+rel="stylesheet"\s+type="text/css"\s+'
        r'href="(?:\.\./\.\./)?commonltr\.css"\s*/>\s*',
        "\n",
        text,
        flags=re.I,
    )


def process_zip(repo: Path, zip_path: Path) -> tuple[str, str, str]:
    match = ZIP_RE.match(zip_path.name)

    if not match:
        fail(f"Unexpected ZIP filename: {zip_path.name}")

    release = match.group("release").upper()
    domain = match.group("domain").upper()
    domain_dir = DOMAIN_DIR[domain]

    with tempfile.TemporaryDirectory() as td:
        temp = Path(td)

        with zipfile.ZipFile(zip_path) as zf:
            safe_extract(zf, temp)

        landing = temp / f"{release}_Fusion_{domain}_Analytics_Tables.html"
        topic_refs = temp / "topic_refs"
        book_css = temp / "book.css"

        if not landing.is_file():
            fail(
                f"{zip_path.name}: missing expected landing page "
                f"{landing.name}"
            )

        if not topic_refs.is_dir():
            fail(f"{zip_path.name}: missing topic_refs directory")

        if not book_css.is_file():
            fail(f"{zip_path.name}: missing book.css")

        topic_files = list(topic_refs.glob("*.html"))

        if not topic_files:
            fail(f"{zip_path.name}: topic_refs contains no HTML files")

        landing_text = landing.read_text(encoding="utf-8-sig")
        landing_text = remove_dead_commonltr(landing_text)
        landing_text = landing_text.replace(
            'href="topic_refs/',
            f'href="{domain_dir}/',
        )

        # Remove the previous published landing page for this domain.
        for old in repo.glob(f"*_Fusion_{domain}_Analytics_Tables.html"):
            old.unlink()

        # Replace the previous domain topic directory.
        target_dir = repo / domain_dir

        if target_dir.exists():
            shutil.rmtree(target_dir)

        target_dir.mkdir(parents=True)

        for src in topic_files:
            text = src.read_text(encoding="utf-8-sig")
            text = remove_dead_commonltr(text)

            (target_dir / src.name).write_text(
                text,
                encoding="utf-8",
                newline="\n",
            )

        (repo / landing.name).write_text(
            landing_text,
            encoding="utf-8",
            newline="\n",
        )

        shutil.copy2(book_css, repo / "book.css")

    return domain, release, landing.name


def build_readme(updates: dict[str, tuple[str, str]]) -> str:
    """
    Generate README.md from the releases actually supplied.

    All three domains are required so the README can never publish
    a mixed-release homepage accidentally.
    """

    required_domains = {"ERP", "HCM", "SCM"}
    supplied_domains = set(updates)

    missing = required_domains - supplied_domains

    if missing:
        fail(
            "README generation requires ERP, HCM, and SCM ZIPs in the same run. "
            f"Missing: {', '.join(sorted(missing))}"
        )

    erp_release, erp_html = updates["ERP"]
    hcm_release, hcm_html = updates["HCM"]
    scm_release, scm_html = updates["SCM"]

    # Oracle documentation URLs expect lowercase release tokens.
    erp_r = erp_release.lower()
    hcm_r = hcm_release.lower()
    scm_r = scm_release.lower()

    return f"""# Oracle Fusion Data Intelligence Data Catalog

- [ERP Tables](/{erp_html})
- [HCM Tables](/{hcm_html})
- [SCM Tables](/{scm_html})

This is a convenience site that publishes the Oracle Fusion Data Intelligence
table catalogs supplied by Oracle.

## Oracle Documentation

### HR (HCM) Data

https://docs.oracle.com/en/cloud/saas/analytics/{hcm_r}/fahia/

### Finance (ERP) Data

https://docs.oracle.com/en/cloud/saas/analytics/{erp_r}/faiae/

### Procurement / Supply Chain (SCM) Data

https://docs.oracle.com/en/cloud/saas/analytics/{scm_r}/fascm/

## Mapping from Fusion SaaS to FDI

Oracle calls these spreadsheets "Data Augmentation." They contain Fusion
entities and tables and their corresponding FDI objects.

### HCM

https://docs.oracle.com/en/cloud/saas/analytics/{hcm_r}/fahia/chapter-data-augmentation.html

### ERP

https://docs.oracle.com/en/cloud/saas/analytics/{erp_r}/faiae/data-augmentation.html

### SCM

https://docs.oracle.com/en/cloud/saas/analytics/{scm_r}/fascm/chapter-data-augmentation.html
"""


def update_readme(
    repo: Path,
    updates: dict[str, tuple[str, str]],
) -> None:
    readme = repo / "README.md"

    readme.write_text(
        build_readme(updates),
        encoding="utf-8",
        newline="\n",
    )

    print("Updated README.md from supplied Oracle releases")


def validate(
    repo: Path,
    updates: dict[str, tuple[str, str]],
) -> None:
    errors: list[str] = []

    for domain, (release, html_name) in updates.items():
        domain_dir = DOMAIN_DIR[domain]
        landing = repo / html_name

        if not landing.is_file():
            errors.append(f"{html_name}: landing page does not exist")
            continue

        text = landing.read_text(encoding="utf-8")

        if "commonltr.css" in text:
            errors.append(
                f"{html_name}: still references missing commonltr.css"
            )

        refs = re.findall(
            r'href="([^"#?]+\.html)"',
            text,
            flags=re.I,
        )

        for ref in refs:
            target = (repo / ref).resolve()

            if not target.is_file():
                errors.append(
                    f"{html_name}: broken link {ref}"
                )

        topic_dir = repo / domain_dir

        if not topic_dir.is_dir():
            errors.append(
                f"{domain_dir}: expected topic directory is missing"
            )
            continue

        for topic in topic_dir.glob("*.html"):
            topic_text = topic.read_text(encoding="utf-8")

            if "commonltr.css" in topic_text:
                errors.append(
                    f"{topic.relative_to(repo)}: "
                    "still references missing commonltr.css"
                )

            if 'href="../book.css"' not in topic_text:
                errors.append(
                    f"{topic.relative_to(repo)}: "
                    "missing expected ../book.css reference"
                )

    # Validate README against the actual ZIP releases.
    readme = repo / "README.md"

    if not readme.is_file():
        errors.append("README.md is missing")
    else:
        readme_text = readme.read_text(encoding="utf-8")

        for domain, (release, html_name) in updates.items():
            expected_catalog_link = f"](/" + html_name + ")"

            if expected_catalog_link not in readme_text:
                errors.append(
                    f"README.md: missing {domain} catalog link "
                    f"to {html_name}"
                )

            release_lower = release.lower()
            guide = DOC_INFO[domain]["guide"]

            expected_docs = (
                f"docs.oracle.com/en/cloud/saas/analytics/"
                f"{release_lower}/{guide}/"
            )

            if expected_docs not in readme_text:
                errors.append(
                    f"README.md: missing {domain} {release} "
                    "Oracle documentation link"
                )

    if errors:
        fail(
            "Validation failed:\n"
            + "\n".join(errors[:100])
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Publish Oracle FDI analytics table ZIPs "
            "into this GitHub Pages repo."
        )
    )

    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
    )

    parser.add_argument(
        "--incoming",
        type=Path,
        default=Path("incoming"),
    )

    parser.add_argument(
        "--delete-zips",
        action="store_true",
    )

    args = parser.parse_args()

    repo = args.repo.resolve()

    incoming = (
        args.incoming
        if args.incoming.is_absolute()
        else repo / args.incoming
    )

    zips = sorted(incoming.glob("*.zip"))

    if not zips:
        fail(f"No ZIP files found in {incoming}")

    updates: dict[str, tuple[str, str]] = {}

    for zip_path in zips:
        domain, release, html_name = process_zip(
            repo,
            zip_path,
        )

        if domain in updates:
            fail(
                f"More than one {domain} ZIP supplied "
                "in the same run"
            )

        updates[domain] = (
            release,
            html_name,
        )

        print(
            f"Prepared {domain} {release}: {html_name}"
        )

    # Require the complete three-domain release package.
    expected = {"ERP", "HCM", "SCM"}

    if set(updates) != expected:
        missing = expected - set(updates)

        fail(
            "Upload all three Oracle catalog ZIPs together. "
            f"Missing: {', '.join(sorted(missing))}"
        )

    update_readme(repo, updates)
    validate(repo, updates)

    if args.delete_zips:
        for zip_path in zips:
            zip_path.unlink()

    summary = ", ".join(
        f"{domain} {release}"
        for domain, (release, _) in sorted(updates.items())
    )

    print(f"Catalog update complete: {summary}")


if __name__ == "__main__":
    main()