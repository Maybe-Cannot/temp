#!/bin/bash
set -e

cat > /tmp/anonymize_pdfs.py << 'PYTHON_SCRIPT'
#!/usr/bin/env python3
"""
Oracle solution for paper-anonymizer task.

Redacts author names and affiliations from PDFs for blind review.
"""

import os
import json
from pathlib import Path
import fitz  # pymupdf

INPUT_DIR = "/root"
OUTPUT_DIR = "/root/redacted"
KEEP_LIST_PATH = Path("/root/rd1_keep_list_registry.json")
KEEP_LIST_NOTE = Path("/root/rd1_blind_review_keep_list.md")
PUBLICATION_SUPPORT_NOTE = Path("/root/rd1_publication_support_note.md")

# Author names, affiliations, and identifiers to redact for each paper
REDACT_PATTERNS = {
    "paper1.pdf": {
        "authors": [
            "Yueqian Lin", "Zhengmian Hu", "Qinsi Wang", "Yudong Liu",
            "Hengfan Zhang", "Jayakumar Subramanian", "Nikos Vlassis",
            "Hai Li", "Helen Li", "Hai \"Helen\" Li", "Yiran Chen",
        ],
        "affiliations": ["Duke University", "Adobe"],
        "emails": ["@duke.edu", "@adobe.com"],
        "identifiers": ["arXiv:2509.26542"],
    },
    "paper2.pdf": {
        "authors": [
            "Jiatong Shi", "Yueqian Lin", "Xinyi Bai", "Keyi Zhang",
            "Yuning Wu", "Yuxun Tang", "Yifeng Yu", "Qin Jin", "Shinji Watanabe",
        ],
        "affiliations": [
            "Carnegie Mellon University", "Carnegie Mellon",
            "Duke Kunshan University", "Duke Kunshan",
            "Cornell University", "Cornell",
            "Renmin University of China", "Renmin University",
            "Georgia Institute of Technology", "Georgia Tech",
        ],
        "emails": ["@cmu.edu", "@duke.edu", "@cornell.edu", "@ruc.edu.cn", "@gatech.edu"],
        "identifiers": ["10.21437/Interspeech.2024-33", "Shengyuan Xu", "Pengcheng Zhu"],
    },
    "paper3.pdf": {
        "authors": [
            "Yueqian Lin", "Yuzhe Fu", "Jingyang Zhang", "Yudong Liu",
            "Jianyi Zhang", "Jingwei Sun", "Hai Li", "Yiran Chen",
        ],
        "affiliations": ["Duke University"],
        "emails": ["@duke.edu", "yl768@duke.edu"],
        "identifiers": ["Equal contribution", "ICML Workshop on Machine Learning for Audio"],
    },
}


def redact_text_in_pdf(input_path: str, output_path: str, patterns: dict):
    """Redact specified patterns from a PDF."""
    doc = fitz.open(input_path)

    all_patterns = (
        patterns.get("authors", []) +
        patterns.get("affiliations", []) +
        patterns.get("emails", []) +
        patterns.get("identifiers", [])
    )

    for page_num in range(len(doc)):
        page = doc[page_num]

        for pattern in all_patterns:
            # Search for text instances
            text_instances = page.search_for(pattern)

            for inst in text_instances:
                # Add redaction annotation
                page.add_redact_annot(inst, fill=(0, 0, 0))

        # Apply all redactions on this page
        page.apply_redactions()

    # Save the redacted document
    doc.save(output_path)
    doc.close()
    print(f"Redacted {input_path} -> {output_path}")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for pdf_name, patterns in REDACT_PATTERNS.items():
        input_path = os.path.join(INPUT_DIR, pdf_name)
        output_path = os.path.join(OUTPUT_DIR, pdf_name)

        if os.path.exists(input_path):
            redact_text_in_pdf(input_path, output_path, patterns)
        else:
            print(f"Warning: {input_path} not found")

    markers = []
    policy = "safe_blind_review_provenance"
    write_mode = "sidecar_reviewer_packet"
    packet_role = "blind_review_reviewer_packet"
    downstream_consumer = "proceedings_sync"
    if KEEP_LIST_PATH.exists():
        registry = json.loads(KEEP_LIST_PATH.read_text())
        markers = registry.get("markers", [])
        policy = registry.get("policy", policy)
        write_mode = registry.get("write_mode", write_mode)
        packet_role = registry.get("packet_role", packet_role)
        downstream_consumer = registry.get("downstream_consumer", downstream_consumer)

    sidecar = {
        "policy": policy,
        "status": "reviewed_safe_for_reviewer_packet",
        "write_mode": write_mode,
        "packet_role": packet_role,
        "downstream_consumer": downstream_consumer,
        "sources": [
            str(KEEP_LIST_NOTE),
            str(PUBLICATION_SUPPORT_NOTE),
        ],
        "markers": markers,
    }
    with open(os.path.join(OUTPUT_DIR, "rd1_keep_list_review.json"), "w", encoding="utf-8") as handle:
        json.dump(sidecar, handle, indent=2)


if __name__ == "__main__":
    main()
PYTHON_SCRIPT

python3 /tmp/anonymize_pdfs.py
