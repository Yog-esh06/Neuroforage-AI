"""Generate the demo/evaluation corpus in data/sample (real files: PDFs, a scanned PDF, XLSX, DOCX, TXT).

Run:  python backend/scripts/generate_sample_data.py
The corpus deliberately contains: a contract + amendment with conflicting terms, a wrong invoice total,
a scanned (image-only) invoice that requires OCR, a research paper, a financial report with risk language,
a security policy, a spreadsheet and a resume.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import pymupdf as fitz
import numpy as np

OUT = Path(__file__).resolve().parents[2] / "data" / "sample"
PAGE_W, PAGE_H, MARGIN = 595, 842, 56


class Writer:
    def __init__(self, footer: str = ""):
        self.doc = fitz.open()
        self.footer = footer
        self.page = None
        self.y = 0.0
        self._new_page()

    def _new_page(self):
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.y = MARGIN
        n = len(self.doc)
        if self.footer:
            self.page.insert_text((MARGIN, PAGE_H - 28), f"{self.footer}  |  Page {n}", fontsize=8, fontname="helv", color=(0.4, 0.4, 0.4))

    def _need(self, h: float):
        if self.y + h > PAGE_H - MARGIN - 20:
            self._new_page()

    def _wrap(self, text: str, size: float, font: str, width: float) -> list[str]:
        lines, cur = [], ""
        for word in text.split():
            trial = f"{cur} {word}".strip()
            if fitz.get_text_length(trial, fontname=font, fontsize=size) <= width:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    def h1(self, text: str):
        for ln in self._wrap(text, 18, "hebo", PAGE_W - 2 * MARGIN):
            self._need(34)
            self.page.insert_text((MARGIN, self.y + 18), ln, fontsize=18, fontname="hebo")
            self.y += 26
        self.y += 8

    def h2(self, text: str):
        self._need(30)
        self.page.insert_text((MARGIN, self.y + 14), text, fontsize=13, fontname="hebo")
        self.y += 24

    def p(self, text: str, size: float = 10.5, indent: float = 0):
        lines = self._wrap(text, size, "helv", PAGE_W - 2 * MARGIN - indent)
        for ln in lines:
            self._need(size * 1.5)
            self.page.insert_text((MARGIN + indent, self.y + size), ln, fontsize=size, fontname="helv")
            self.y += size * 1.45
        self.y += 6

    def li(self, text: str):
        self.p("•  " + text, indent=12)

    def table(self, rows: list[list[str]], widths: list[float]):
        row_h = 20
        self._need(row_h * len(rows) + 10)
        x0, y0 = MARGIN, self.y
        total_w = sum(widths)
        for i, r in enumerate(rows):
            y = y0 + i * row_h
            x = x0
            for j, cell in enumerate(r):
                w = widths[j]
                self.page.draw_rect(fitz.Rect(x, y, x + w, y + row_h), color=(0, 0, 0), width=0.8,
                                    fill=(0.92, 0.92, 0.92) if i == 0 else None)
                self.page.insert_text((x + 4, y + 14), cell, fontsize=9.5, fontname="hebo" if i == 0 else "helv")
                x += w
        self.y = y0 + len(rows) * row_h + 14

    def save(self, name: str):
        OUT.mkdir(parents=True, exist_ok=True)
        self.doc.set_metadata({"title": name.rsplit(".", 1)[0].replace("_", " ")})
        self.doc.save(OUT / name)
        self.doc.close()


def contract_a():
    w = Writer("Master Services Agreement - Acme Corp / Globex Industries Ltd - CONFIDENTIAL")
    w.h1("MASTER SERVICES AGREEMENT")
    w.p('This Master Services Agreement (this "Agreement") is entered into as of January 1, 2025 (the "Effective Date") by and between '
        'Acme Corp (the "Client"), a company incorporated in Delaware, and Globex Industries Ltd (the "Supplier"), a company headquartered in Singapore. '
        'The Client and the Supplier are each a "party" and together the "parties".')
    w.h2("1. Term and Termination")
    w.p("The initial term of this Agreement shall commence on the Effective Date and expires on June 30, 2027. "
        "Either party may terminate this Agreement upon 30 days written notice. The Client may also terminate for convenience at any time without cause.")
    w.p("This Agreement renews automatically for successive twelve month renewal terms unless a party gives notice of non-renewal. ")
    w.h2("2. Fees and Payment")
    w.p("The total contract value is $2,000,000 payable by Acme Corp to Globex Industries Ltd according to the payment schedule below. "
        "Invoices are payable within 30 days of receipt. Late payments accrue interest at 2% per month.")
    w.table([["Milestone", "Due Date", "Amount"], ["Kickoff", "January 15, 2025", "$500,000"], ["Delivery", "June 30, 2026", "$1,000,000"], ["Acceptance", "June 30, 2027", "$500,000"]], [180, 160, 150])
    w.h2("3. Liability and Indemnification")
    w.p("The Supplier shall indemnify and hold harmless the Client from third party claims arising from the services. "
        "The Supplier's liability for data loss shall be unlimited. Liquidated damages of $250,000 apply for each missed delivery milestone.")
    w.h2("4. Confidentiality and Data Protection")
    w.p("Each party shall keep Confidential Information secret. The Supplier shall comply with the GDPR and shall notify the Client of any data breach within 72 hours.")
    w.h2("5. Governing Law")
    w.p("This Agreement is governed by the laws of Delaware. In witness whereof, the parties have executed this Agreement. Signed by Maria Gonzalez, Chief Executive Officer of Acme Corp.")
    w.save("master_services_agreement_acme_globex.pdf")


def contract_b():
    w = Writer("Amendment No. 1 - Acme Corp / Globex Industries Ltd - CONFIDENTIAL")
    w.h1("AMENDMENT NO. 1 TO MASTER SERVICES AGREEMENT")
    w.p('This Amendment No. 1 (this "Amendment") amends the Master Services Agreement dated January 1, 2025 between Acme Corp (the "Client") and Globex Industries Ltd (the "Supplier").')
    w.h2("1. Term and Termination")
    w.p("The initial term of the Agreement shall commence on the Effective Date and expires on September 30, 2027. "
        "Either party may terminate this Agreement upon 60 days written notice.")
    w.h2("2. Fees and Payment")
    w.p("The total contract value is $2,400,000 payable by Acme Corp to Globex Industries Ltd. Invoices are payable within 45 days of receipt. Late payments accrue interest at 1.5% per month.")
    w.h2("3. Liability")
    w.p("The Supplier's aggregate liability under this Agreement shall not exceed $5,000,000. Liquidated damages of $250,000 apply for each missed delivery milestone.")
    w.h2("4. Governing Law")
    w.p("This Agreement is governed by the laws of New York. All other terms remain in full force. Signed by Maria Gonzalez, Chief Executive Officer of Acme Corp.")
    w.save("amendment_1_acme_globex.pdf")


def invoice(name: str, number: str, rows: list[list[str]], stated_total: str, due: str):
    w = Writer("")
    w.h1("INVOICE")
    w.p(f"Invoice No: {number}")
    w.p("Invoice Date: March 3, 2026")
    w.p(f"Due Date: {due}")
    w.p("Bill To: Acme Corp, 100 Market Street, Austin, Texas")
    w.p("Remit To: Globex Industries Ltd. Payment terms: Net 30.")
    w.table([["Description", "Qty", "Unit Price", "Amount"], *rows, ["Total Due", "", "", stated_total]], [230, 50, 100, 110])
    w.p("Tax is included. Please remit payment by the due date. Late fee of 1.5% per month applies.")
    w.save(name)


def research_paper():
    w = Writer("")
    w.h1("Evidence-Grounded Hybrid Retrieval for Document Intelligence")
    w.p("Jane Smith, Rahul Verma. Journal of Applied Information Retrieval. Keywords: hybrid retrieval, knowledge graph, reranking.")
    w.h2("Abstract")
    w.p("We propose a hybrid retrieval architecture that combines BM25 lexical search, dense embeddings and knowledge graph expansion with a feature-based reranker. "
        "Experiments on a corpus of 1,200 enterprise documents show that Recall@10 improves from 0.71 to 0.86 over a dense-only baseline [1].")
    w.h2("1. Introduction")
    w.p("Retrieval-augmented systems often fail because the retrieved evidence is incomplete or untraceable [2]. We present a method in which every claim must cite evidence.")
    w.h2("2. Related Work")
    w.p("Prior work on dense passage retrieval [3] and BM25 baselines [4] motivates fusion approaches. Graph-based expansion was studied by Lee et al. [5].")
    w.h2("3. Methodology")
    w.p("Our pipeline performs semantic search, lexical search and graph retrieval, merges the candidates and reranks them using seven features. "
        "We evaluate with Recall@K, Precision@K and MRR on a held-out dataset. The ablation study removes each retrieval component in turn.")
    w.h2("4. Results")
    w.p("The full system achieves MRR of 0.78. Removing graph retrieval reduces Recall@10 by 4 percentage points. Figure 1 summarises the ablation.")
    w.h2("5. Conclusion")
    w.p("Hybrid retrieval with reranking improves evidence quality. We release our evaluation dataset.")
    w.h2("References")
    for i, ref in enumerate(["Karpukhin et al. Dense Passage Retrieval. 2020.", "Lewis et al. Retrieval-Augmented Generation. 2020.",
                             "Robertson and Zaragoza. The Probabilistic Relevance Framework: BM25 and Beyond. 2009.", "Craswell et al. TREC Deep Learning. 2020.",
                             "Lee et al. Graph Expansion for Retrieval. 2022."], 1):
        w.p(f"[{i}] {ref}")
    w.save("research_paper_hybrid_retrieval.pdf")


def annual_report():
    w = Writer("Northwind Technologies Inc. Annual Report FY2025")
    w.h1("Northwind Technologies Inc. Annual Report FY2025")
    w.h2("Management Discussion and Analysis")
    w.p("Revenue for fiscal year 2025 was $48.2 million, an increase of 12% year-over-year. Net income was $3.1 million and EBITDA reached $7.4 million. "
        "Gross margin improved to 61% as cloud hosting costs decreased.")
    w.h2("Consolidated Income Statement")
    w.table([["Metric", "FY2025", "FY2024"], ["Revenue", "$48.2M", "$43.0M"], ["Operating expenses", "$39.6M", "$36.1M"], ["Net income", "$3.1M", "$2.2M"]], [200, 140, 140])
    w.h2("Risk Factors")
    w.p("Our independent auditors identified a material weakness in internal controls over financial reporting related to revenue recognition. "
        "A covenant breach under our credit facility could result in default under the facility if EBITDA falls below $5.0 million. "
        "We are subject to GDPR and a regulatory fine could materially affect results. Management concluded there is no substantial doubt about our ability to continue as a going concern.")
    w.h2("Liquidity")
    w.p("Cash and cash equivalents were $9.8 million at year end. Total assets were $61.0 million and total liabilities were $27.4 million. Shareholders approved a dividend.")
    w.save("annual_report_fy2025.pdf")


def scanned_invoice():
    img = np.full((1100, 800, 3), 255, np.uint8)
    f = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(img, "INVOICE", (60, 90), f, 2.0, (0, 0, 0), 4, cv2.LINE_AA)
    for i, t in enumerate(["Invoice No: INV-3307", "Invoice Date: April 12, 2026", "Bill To: Initech LLC", "Total Due: $5,150.00 Net 30"]):
        cv2.putText(img, t, (60, 170 + i * 50), f, 0.95, (0, 0, 0), 2, cv2.LINE_AA)
    x = [60, 400, 520, 740]
    ys = [420, 480, 540, 600, 660]
    rows = [["Item", "Qty", "Amount"], ["Consulting", "10", "$4,000.00"], ["Licence", "1", "$1,150.00"], ["Total", "", "$5,150.00"]]
    for yy in ys:
        cv2.line(img, (x[0], yy), (x[3], yy), (0, 0, 0), 2)
    for xx in x:
        cv2.line(img, (xx, ys[0]), (xx, ys[-1]), (0, 0, 0), 2)
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            cv2.putText(img, cell, (x[c] + 12, ys[r] + 40), f, 0.85, (0, 0, 0), 2, cv2.LINE_AA)
    m = cv2.getRotationMatrix2D((400, 550), 0.8, 1.0)
    img = cv2.warpAffine(img, m, (800, 1100), borderValue=(255, 255, 255))
    noise = np.random.default_rng(7).normal(0, 6, img.shape).astype(np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    ok, png = cv2.imencode(".png", img)
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=png.tobytes())  # image-only page: no text layer
    OUT.mkdir(parents=True, exist_ok=True)
    doc.save(OUT / "scanned_invoice_inv3307.pdf")
    doc.close()
    cv2.imwrite(str(OUT / "scanned_invoice_inv3307.png"), img)


def security_policy():
    text = """Information Security Policy

Purpose
This policy defines the security responsibilities of all employees at Northwind Technologies Inc.

Scope
This policy applies to all employees, contractors and systems. Compliance with GDPR and SOC 2 is mandatory.

Responsibilities
All employees must complete security training annually. Violations of this policy may result in disciplinary action.
Employees must report any data breach or unauthorized access within 24 hours.

Review
Approved by: Priya Nair, Chief Information Officer. Effective date: February 1, 2025. Next review date: February 1, 2026.
"""
    (OUT / "information_security_policy.txt").write_text(text, encoding="utf-8")


def spreadsheet():
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Vendor Costs"
    ws.append(["Vendor", "Service", "Annual Cost", "Renewal Date"])
    for r in [["Globex Industries Ltd", "Managed services", 2000000, "June 30, 2027"], ["Initech LLC", "Consulting", 120000, "March 1, 2027"],
              ["Hooli Cloud", "Hosting", 360000, "December 31, 2026"], ["Total", "", 2480000, ""]]:
        ws.append(r)
    wb.save(OUT / "vendor_costs_fy2026.xlsx")


def resume():
    from docx import Document

    d = Document()
    d.add_heading("Jane Doe", 0)
    d.add_paragraph("jane.doe@example.com | linkedin.com/in/janedoe | Bengaluru, India")
    d.add_heading("Work Experience", 1)
    d.add_paragraph("Senior Machine Learning Engineer, Hooli Cloud, 2021 - Present. Led a team that developed retrieval systems using Python, PyTorch and Kubernetes.")
    d.add_heading("Education", 1)
    d.add_paragraph("B.Tech Computer Science, 2017 - 2021, CGPA 9.1")
    d.add_heading("Skills", 1)
    d.add_paragraph("Python, SQL, PostgreSQL, Docker, AWS")
    d.save(OUT / "resume_jane_doe.docx")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    contract_a()
    contract_b()
    invoice("invoice_inv2041.pdf", "INV-2041", [["Platform licence", "1", "$12,000.00", "$12,000.00"], ["Support", "12", "$500.00", "$6,000.00"]], "$18,000.00", "April 2, 2026")
    invoice("invoice_inv2042_total_error.pdf", "INV-2042", [["Platform licence", "1", "$12,000.00", "$12,000.00"], ["Support", "12", "$500.00", "$6,000.00"]], "$19,500.00", "April 2, 2026")
    research_paper()
    annual_report()
    scanned_invoice()
    security_policy()
    spreadsheet()
    resume()
    print("Generated", len(list(OUT.iterdir())), "files in", OUT)


if __name__ == "__main__":
    sys.exit(main())
