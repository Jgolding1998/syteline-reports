"""
SyteLine Reporting Application
==============================

This FastAPI application provides a simple front‑end for generating
reports and performing ad‑hoc queries against an Infor CloudSuite
Industrial (SyteLine) REST/OData API.  The application is designed
to be flexible: if connection information (base URL, configuration
group and site, and an API token) is provided via environment
variables, the app will attempt to fetch data directly from the
SyteLine API.  If not, or if a call fails, it will fall back to
dummy sample data so the site remains functional without a live
connection.

Environment variables used:

  SYTELINE_BASE_URL    The base URL for the SyteLine REST API,
                       e.g. ``https://<tenant>.inforcloudsuite.com/idoapi``.
  SYTELINE_CONFIG      The configuration group and site to use for
                       API calls, in the form ``ConfigGroup:Site``.
  SYTELINE_TOKEN       A token string to include in the
                       ``Authorization`` header.  The API expects the
                       header ``Authorization: Mongoose <token>``.

Note: These credentials should be set securely on the hosting
environment.  Do not commit secrets to version control.

The app exposes three routes:

* ``GET /`` – Render the index page with forms for a sales report
  and a generic query.
* ``POST /sales_report`` – Generate a sales summary over a date
  range, grouped by day, month or year.  Uses dummy data if the
  SyteLine API is unavailable.
* ``POST /query`` – Perform an ad‑hoc query against a specified
  IDO, returning selected properties and allowing optional filter
  and order by expressions.  If the API call fails, no results
  are returned.

You can run the application locally with ``uvicorn app:app --reload``.
"""

import os
from datetime import datetime
from typing import List, Dict, Any

import requests
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


app = FastAPI()

# Configure the Jinja2 templates directory
templates = Jinja2Templates(directory="templates")

# Read configuration from environment
BASE_URL = os.getenv("SYTELINE_BASE_URL")
MONGOOSE_CONFIG = os.getenv("SYTELINE_CONFIG")
API_TOKEN = os.getenv("SYTELINE_TOKEN")


def query_ido(ido: str, properties: List[str] | None = None,
              filter_expr: str | None = None,
              order_by: str | None = None,
              record_cap: int = 0) -> List[Dict[str, Any]]:
    """Query a SyteLine IDO collection via the REST API.

    Parameters
    ----------
    ido: str
        The name of the IDO collection to query, e.g. ``SLCustomers``.
    properties: list[str] | None
        A list of property names to return.  If ``None`` or empty,
        all fields will be returned by the API.  When provided, the
        properties will be joined into a comma‑separated string.
    filter_expr: str | None
        An optional filter expression (SQL WHERE clause without
        ``WHERE``) to limit the results, e.g. ``CustNum='C000001'``.
    order_by: str | None
        An optional order by expression, e.g. ``CustNum DESC``.
    record_cap: int
        Limits the number of records returned.  ``0`` means
        unlimited.

    Returns
    -------
    list[dict[str, Any]]
        A list of dictionaries representing the rows returned by
        SyteLine, or an empty list on error.
    """
    if not (BASE_URL and MONGOOSE_CONFIG and API_TOKEN):
        # Missing configuration; cannot call API.
        return []

    # Construct the endpoint URL
    url = f"{BASE_URL.rstrip('/')}/ido/{ido}/load"
    # Build query parameters
    params: Dict[str, Any] = {}
    if properties:
        params["properties"] = ",".join(properties)
    if filter_expr:
        params["filter"] = filter_expr
    if order_by:
        params["orderBy"] = order_by
    # Unlimited records by default
    params["recordCap"] = record_cap

    # Build headers
    headers = {
        "Authorization": f"Mongoose {API_TOKEN}",
        "X-Infor-MongooseConfig": MONGOOSE_CONFIG,
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # SyteLine returns records under the 'items' key for REST
        # v2 endpoints.  Fall back to top level list if not found.
        items = data.get("items") or data
        if isinstance(items, list):
            return items
        return []
    except Exception:
        # On any error, return empty results
        return []


# Dummy sample data for offline use.  Each row contains a
# transaction date (as a string), a sales type (Service/Product/
# Freight/Misc), an amount, and customer/item identifiers.
DUMMY_SALES = [
    {"TransDate": "2026-01-01", "Type": "Product", "Amount": 1200.0, "CustNum": "C0001", "Item": "A100"},
    {"TransDate": "2026-01-01", "Type": "Service", "Amount": 250.0, "CustNum": "C0002", "Item": "SV01"},
    {"TransDate": "2026-01-02", "Type": "Freight", "Amount": 75.0, "CustNum": "C0003", "Item": "FR01"},
    {"TransDate": "2026-01-02", "Type": "Misc", "Amount": 50.0, "CustNum": "C0001", "Item": "MISC"},
    {"TransDate": "2026-01-05", "Type": "Product", "Amount": 800.0, "CustNum": "C0002", "Item": "A200"},
    {"TransDate": "2026-02-01", "Type": "Service", "Amount": 300.0, "CustNum": "C0003", "Item": "SV02"},
]


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render the index page with forms for reports and queries."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/sales_report", response_class=HTMLResponse)
async def sales_report(request: Request,
                       start_date: str = Form(...),
                       end_date: str = Form(...),
                       group_by: str = Form(...)):
    """Generate a sales summary report.

    Parameters are collected from an HTML form.  The report is
    grouped by day, month or year based on the ``group_by`` value.

    If data cannot be retrieved from SyteLine, the function uses
    predefined dummy data (``DUMMY_SALES``) for demonstration
    purposes.
    """
    # Parse dates
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        return templates.TemplateResponse("results.html", {
            "request": request,
            "sales_summary": {},
            "error": "Invalid date format. Please use YYYY-MM-DD."
        })

    # Attempt to load data from SyteLine.  We're guessing an IDO name
    # and properties; adjust these as needed for your environment.
    ido_name = "SLPostedInvoices"  # Example IDO for posted invoices
    properties = ["InvoiceDate", "Type", "Amount", "CustNum"]
    filter_expr = f"InvoiceDate>='{start_date}' AND InvoiceDate<='{end_date}'"
    records = query_ido(ido_name, properties=properties, filter_expr=filter_expr)
    # If no records were returned, fall back to dummy data
    if not records:
        records = DUMMY_SALES
        # Filter dummy data by date range
        records = [row for row in records
                   if start_dt <= datetime.strptime(row["TransDate"], "%Y-%m-%d").date() <= end_dt]
    else:
        # Normalize field names in records from API to match dummy
        for row in records:
            # Rename InvoiceDate to TransDate to simplify grouping
            if "InvoiceDate" in row:
                row["TransDate"] = row.pop("InvoiceDate")
            # Ensure date is ISO string
            if isinstance(row.get("TransDate"), (datetime,)):
                row["TransDate"] = row["TransDate"].strftime("%Y-%m-%d")

    # Group data by chosen period
    summary: Dict[str, float] = {}
    for row in records:
        # Parse transaction date
        try:
            dt = datetime.strptime(row["TransDate"], "%Y-%m-%d")
        except Exception:
            continue
        if group_by == "day":
            key = dt.strftime("%Y-%m-%d")
        elif group_by == "month":
            key = dt.strftime("%Y-%m")
        else:
            key = dt.strftime("%Y")
        summary[key] = summary.get(key, 0.0) + float(row.get("Amount", 0))

    return templates.TemplateResponse("results.html", {
        "request": request,
        "sales_summary": summary,
        "items": None,
        "error": None,
    })


@app.post("/query", response_class=HTMLResponse)
async def generic_query(request: Request,
                        ido: str = Form(...),
                        properties: str = Form(""),
                        filter_expr: str = Form(""),
                        order_by: str = Form("")):
    """Perform an ad‑hoc query against a given IDO.

    Users can specify the IDO name, a comma‑separated list of
    properties, an optional filter expression, and an optional order
    by string.  The results are displayed in a simple HTML table.
    """
    prop_list = [p.strip() for p in properties.split(",") if p.strip()]
    filter_val = filter_expr if filter_expr else None
    order_val = order_by if order_by else None
    results = query_ido(ido, properties=prop_list or None,
                        filter_expr=filter_val,
                        order_by=order_val)
    return templates.TemplateResponse("results.html", {
        "request": request,
        "sales_summary": None,
        "items": results,
        "error": None,
    })
