"""
SystemaOps service catalogue for opportunity matching.
Based on: https://www.systemaops.com
Pricing: $25-49/hr | Min project: ~$5,000
"""
from typing import List, Dict

SYSTEMAOPS_SERVICES: Dict[str, Dict] = {
    "odoo_erp": {
        "name": "Odoo ERP Solutions",
        "description": (
            "Full Odoo ERP implementation, customization, and integration including CRM, "
            "Sales, Inventory, HR, Payroll, and Accounting modules. Covers migrations from "
            "legacy systems and custom Odoo module development."
        ),
        "sub_services": [
            "Odoo Implementation", "Odoo CRM", "Odoo Inventory", "Odoo Sales",
            "Odoo HR & Payroll", "Odoo Accounting", "Odoo Customization",
            "Odoo Integration", "ERP Migration",
        ],
        "ideal_for": [
            "manufacturing", "wholesale", "distribution", "retail", "logistics",
            "trading", "construction", "automotive", "food", "pharmaceutical",
        ],
        "pain_points": [
            "manual inventory tracking", "disconnected systems", "no ERP",
            "spreadsheet-based operations", "manual invoicing", "no accounting software",
            "stock management problems", "purchasing without automation",
        ],
        "keywords": [
            "erp", "inventory", "accounting", "crm", "sales management", "hr",
            "payroll", "warehouse", "manufacturing", "purchase", "stock", "supply chain",
        ],
    },
    "ai_automation": {
        "name": "AI & Intelligent Automation",
        "description": (
            "AI workflow implementation, LLM orchestration, AI agents, WhatsApp bots, "
            "generative AI solutions, and AI-powered business process automation with "
            "OpenAI and Claude integration."
        ),
        "sub_services": [
            "AI Workflow Implementation", "AI Agents", "WhatsApp Business Bot",
            "LLM Orchestration", "Generative AI Solutions", "AI Monitoring & Maintenance",
            "Intelligent Customer Support",
        ],
        "ideal_for": [
            "customer service", "sales teams", "lead generation", "content creation",
            "data processing", "ecommerce", "hospitality", "real estate",
        ],
        "pain_points": [
            "manual customer support", "slow lead response time", "repetitive tasks",
            "no automation", "high support volume", "no chatbot", "manual follow-ups",
        ],
        "keywords": [
            "chatbot", "ai", "automation", "whatsapp", "customer service",
            "support bot", "intelligent", "llm", "gpt", "agent",
        ],
    },
    "document_automation": {
        "name": "Document Automation",
        "description": (
            "Automated document intake, extraction, validation, normalization, and routing. "
            "Invoice and RFQ processing with Odoo integration and human-in-the-loop "
            "exception handling."
        ),
        "sub_services": [
            "Invoice Processing Automation", "RFQ Automation", "OCR Data Extraction",
            "Document Routing", "Data Validation", "Duplicate Detection",
            "Odoo Document Integration",
        ],
        "ideal_for": [
            "accounting firms", "manufacturing", "procurement teams", "logistics",
            "wholesale", "import/export", "legal", "medical",
        ],
        "pain_points": [
            "manual invoice entry", "document processing backlog", "data entry errors",
            "slow approval workflows", "paper-based processes", "manual purchase orders",
        ],
        "keywords": [
            "invoice", "document", "ocr", "purchase order", "rfq", "procurement",
            "approval workflow", "accounts payable", "accounts receivable",
        ],
    },
    "workflow_integration": {
        "name": "Workflow Automation & Integration",
        "description": (
            "n8n automation, API integrations, connecting business applications including "
            "Shopify, WooCommerce, Slack, WhatsApp, payment gateways, and logistics systems. "
            "Workflow orchestration and system integration."
        ),
        "sub_services": [
            "n8n Automation", "API Integration", "Shopify Integration",
            "WooCommerce Integration", "Payment Gateway Integration",
            "CRM Integration", "Workflow Orchestration", "System Connectivity",
        ],
        "ideal_for": [
            "ecommerce", "saas companies", "it firms", "marketing agencies",
            "service businesses", "startups", "digital businesses",
        ],
        "pain_points": [
            "manual data transfer between systems", "disconnected apps",
            "no integrations", "copy-paste workflows", "data silos",
            "manual order processing",
        ],
        "keywords": [
            "shopify", "woocommerce", "api", "integration", "webhook",
            "n8n", "workflow", "connect", "sync", "zapier", "automate",
        ],
    },
    "ai_data_testing": {
        "name": "AI Data & Testing Services",
        "description": (
            "AI data annotation, labeling, model validation, and testing automation "
            "for AI/ML projects. Quality assurance for AI systems."
        ),
        "sub_services": [
            "Data Annotation & Labeling", "AI Model Testing", "Model Validation",
            "Testing Automation", "QA for AI Systems",
        ],
        "ideal_for": [
            "tech companies", "ai startups", "research firms", "software companies",
            "ml teams",
        ],
        "pain_points": [
            "ai model quality issues", "data labeling bottlenecks",
            "testing gaps in ai systems", "model accuracy problems",
        ],
        "keywords": [
            "machine learning", "ml", "ai model", "dataset", "annotation",
            "testing", "validation", "neural network", "data science",
        ],
    },
    "technical_solutions": {
        "name": "Technical & Software Solutions",
        "description": (
            "Python development, custom software development, cloud and DevOps engineering, "
            "deployment, system maintenance, and Playwright testing."
        ),
        "sub_services": [
            "Python Development", "Custom Software Development", "Cloud/DevOps",
            "Server Deployment", "System Maintenance", "Playwright Testing",
            "API Development",
        ],
        "ideal_for": [
            "tech startups", "software companies", "digital agencies",
            "businesses needing custom tools", "companies with legacy systems",
        ],
        "pain_points": [
            "no in-house tech team", "legacy system limitations",
            "slow manual deployments", "no automated testing", "custom feature needs",
        ],
        "keywords": [
            "python", "software", "development", "cloud", "devops",
            "deployment", "testing", "custom", "api", "backend",
        ],
    },
}


def match_services(
    business_type: str = "",
    industry: str = "",
    website: str = "",
    signals: List[str] = None,
) -> List[str]:
    """Return ordered list of relevant service keys for a business."""
    signals = signals or []
    text = " ".join([business_type, industry, " ".join(signals)]).lower()

    scored = []
    for key, svc in SYSTEMAOPS_SERVICES.items():
        score = 0
        for kw in svc["keywords"]:
            if kw in text:
                score += 2
        for ind in svc["ideal_for"]:
            if ind in text:
                score += 3
        if score > 0:
            scored.append((key, score))

    scored.sort(key=lambda x: -x[1])

    # Always return at least two relevant suggestions
    if not scored:
        return ["odoo_erp", "workflow_integration"]
    return [k for k, _ in scored]


def get_service(key: str) -> Dict:
    """Return a service dict by key."""
    return SYSTEMAOPS_SERVICES.get(key, {})


def all_services_text() -> str:
    """Return catalogue as formatted text for LLM prompts."""
    lines = []
    for svc in SYSTEMAOPS_SERVICES.values():
        lines.append(f"- {svc['name']}: {svc['description']}")
    return "\n".join(lines)