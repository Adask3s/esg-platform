# Project Overview

Status: internal technical documentation  
Last updated: 2026-05-23  
Extended reference: `SYSTEM_OVERVIEW.md`

## Background

Construction companies face growing requirements around ESG (Environmental, Social, Governance) reporting. The process is often complex, time-consuming, and requires analysis of large volumes of unstructured data from diverse sources. Traditional reporting methods are inefficient and prone to inaccuracies or omission of material information. Furthermore, interpreting complex ESG regulations and standards remains a challenge for many organizations.

## Problem Statement

There is no efficient, AI-assisted tooling tailored to the construction sector that can process heterogeneous document formats, align extracted data with ESG regulatory frameworks, and produce structured reports without heavy manual effort.

## Project Goal

Develop a platform that leverages Large Language Models (LLM) and Retrieval-Augmented Generation (RAG) to support the ESG report generation process for construction-sector companies. The system must handle unstructured document input, interpret ESG regulations, and automate the reporting workflow.

## Functional Requirements

### LLM Integration
- API integration with a selected LLM (currently OpenAI GPT-4 family)
- Use of LLM to analyze and interpret unstructured textual data
- Natural-language report and summary generation from processed data

### Document Processing
- Ingestion and analysis of unstructured data from Excel, PDF, and text documents
- Automatic extraction of key ESG-relevant information from uploaded documents
- Categorization and tagging of ESG-related data

### ESG Knowledge Base
- Implementation and maintenance of a specialized ESG knowledge base for the construction sector
- Coverage of major standards: GRI, SASB, TCFD
- Contextualization of user data against the knowledge base during retrieval

### Report Generation
- Automated creation of ESG reports aligned with recognized standards (GRI, SASB, TCFD)
- Report personalization based on company and project specifics
- Manual validation against the selected standard and PDF export of generated reports

## Scope

The initial scope covers:
- Document ingestion pipeline (PDF, DOCX, XLSX)
- Chunking, embedding, and vector storage
- RAG retrieval combining user documents and the ESG knowledge base
- LLM-based report generation
- Basic user authentication and document management
- Asynchronous task processing via Celery

Out of scope for the initial release:
- Real-time collaboration between multiple users on a single report
- Full report draft editing workflow and persisted report versioning
- Automated regulatory update ingestion
- External data source connectors (ERP, IoT sensors)

## Stakeholders

| Role | Responsibility |
|------|----------------|
| End user (ESG analyst) | Uploads documents, reviews and refines generated reports |
| Platform administrator | Manages knowledge base updates, user accounts |
| Development team | Implements and maintains the platform |
