"""Parsers for real institutional files.

Reads the committed .docx / .xlsx sources in data/real/ and emits the canonical
ingestion JSON defined by contracts/ingestion_v1.schema.json. Data-quality
anomalies are reported, never silently corrected — see CONTEXT.md section 3.5.
"""
