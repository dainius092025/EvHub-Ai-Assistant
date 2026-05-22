"""
Run this script to discover which Odoo models have data.
Useful for finding new data sources (helpdesk, maintenance, etc.) to export.

Usage: python discover.py
"""
import logging
from config import setup_logging, load_config
from odoo_export.client import OdooClient

# Models to always check, even if they seem internal
PRIORITY_PREFIXES = [
    "repair.", "helpdesk.", "knowledge.", "mail.",
    "maintenance.", "project.", "mrp.", "sale.",
    "stock.", "hr.", "survey.", "quality.",
    "fleet.", "account.", "product.", "purchase.",
    "res.partner",
]

# Models already being exported — marked with ✓ in output
EXPORTED_MODELS = {
    "repair.order",
    "helpdesk.ticket",
    "knowledge.article",
    "project.task",
    "quality.check",
    "quality.alert",
    "quality.point",
    "mrp.production",
    "mrp.workorder",
    "mrp.bom",
    "product.template",
    "res.partner",
    "sale.order",
    "sale.order.line",
    "stock.lot",
    "documents.document",
    "purchase.order",
    "purchase.order.line",
    "x_manufacturer",
    "x_model",
    "x_warranty_claim_overv",
    "x_warranty_claim_overv_stage",
    "x_warranty_database",
    "x_warranty_database_stage",
}


def main():
    setup_logging(logging.WARNING)

    config = load_config()
    client = OdooClient(config["url"], config["db"], config["username"], config["api_key"])
    client.verify_connection()

    print("\nFetching model list...")
    all_models = client.execute(
        "ir.model", "search_read",
        domain=[("transient", "=", False)],
        fields=["model", "name"],
    )
    print(f"Total non-transient models: {len(all_models)}\n")

    # Filter to models matching priority prefixes
    relevant = [m for m in all_models if any(m["model"].startswith(p) for p in PRIORITY_PREFIXES)]
    other = [m for m in all_models if m not in relevant]

    print(f"{'MODEL':<45} {'LABEL':<40} {'RECORDS':>8}  {'':5}")
    print("-" * 103)

    results = []
    for m in relevant:
        try:
            count = client.execute(m["model"], "search_count", domain=[])
            results.append((count, m["model"], m["name"]))
        except Exception:
            pass  # model exists but user has no access

    results.sort(reverse=True)
    for count, model, name in results:
        exported = " ✓" if model in EXPORTED_MODELS else ""
        marker = " ★" if count > 0 and not exported else ""
        print(f"{model:<45} {name:<40} {count:>8}  {exported}{marker}")

    print(f"\n--- Other models with records (top 20) ---")
    other_results = []
    for m in other:
        try:
            count = client.execute(m["model"], "search_count", domain=[])
            if count > 0:
                other_results.append((count, m["model"], m["name"]))
        except Exception:
            pass

    other_results.sort(reverse=True)
    for count, model, name in other_results[:20]:
        print(f"{model:<45} {name:<40} {count:>8}")


if __name__ == "__main__":
    main()
