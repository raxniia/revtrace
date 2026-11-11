from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, get_type_hints

from pydantic import BaseModel, Field, ValidationError, create_model

from . import analytics
from .dataset import Dataset, DatasetError
from .model import ConversionModel
from .rag import PolicyIndex


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    fn: Callable[..., dict]
    group: str
    arguments: type[BaseModel]

    @property
    def parameters(self) -> dict:
        schema = self.arguments.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
            options = [o for o in prop.pop("anyOf", []) if o.get("type") != "null"]
            if options:
                prop.update(options[0])
                prop.pop("default", None)
        return schema


def _arguments_model(fn: Callable) -> type[BaseModel]:
    hints = get_type_hints(fn, include_extras=True)
    fields = {
        name: (hints[name], ... if param.default is inspect.Parameter.empty else param.default)
        for name, param in inspect.signature(fn).parameters.items()
    }
    return create_model(f"{fn.__name__}_arguments", **fields)


Month = Annotated[str, Field(description="Month as YYYY-MM")]
OptionalMonth = Annotated[str | None, Field(description="Month as YYYY-MM, or omit for the whole dataset")]
DimensionName = Annotated[str, Field(description="A dimension name returned by list_dimensions")]


class Toolkit:
    def __init__(self, ds: Dataset, index: PolicyIndex, model: ConversionModel):
        self.ds = ds
        self.index = index
        self.model = model
        self.tools: dict[str, Tool] = {}
        self._register()

    def add(self, group: str, description: str):
        def wrap(fn):
            self.tools[fn.__name__] = Tool(fn.__name__, description, fn, group, _arguments_model(fn))
            return fn

        return wrap

    def select(self, *groups: str) -> list[Tool]:
        return [t for t in self.tools.values() if t.group in groups]

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict:
        tool = self.tools.get(name)
        if tool is None:
            return {"error": f"Unknown tool '{name}'"}
        try:
            parsed = tool.arguments(**(arguments or {}))
            return tool.fn(**parsed.model_dump())
        except ValidationError as exc:
            return {"error": "Invalid arguments: " + "; ".join(e["msg"] for e in exc.errors())}
        except DatasetError as exc:
            return {"error": str(exc)}

    def _register(self) -> None:
        ds, index, model = self.ds, self.index, self.model

        @self.add("data", "Leads, sales, conversion rate and revenue for one month.")
        def get_sales_metrics(month: Month) -> dict:
            return analytics.sales_metrics(ds, month)

        @self.add(
            "data",
            "Compare two months: conversion, revenue and lead volume, with the significance of the change.",
        )
        def compare_periods(current: Month, baseline: Month) -> dict:
            return analytics.compare_periods(ds, current, baseline)

        @self.add("data", "List the dimensions leads can be segmented by, with their segments.")
        def list_dimensions() -> dict:
            return {"months": ds.months, "dimensions": ds.describe()["dimensions"]}

        @self.add(
            "data",
            "Test whether a dimension explains the conversion change between two months. Returns conversion "
            "per segment, how the segment mix shifted, and the share of the change attributable to that shift.",
        )
        def test_factor(dimension: DimensionName, current: Month, baseline: Month) -> dict:
            result = analytics.factor_test(ds, dimension, current, baseline)
            result["counterfactual"] = model.counterfactual(dimension, current, baseline)
            return result

        @self.add(
            "data",
            "Median and mean of a numeric lead metric (first_response_minutes, followups_count, price_quoted) "
            "for each segment of a dimension. Use it to find who or what sits behind a factor.",
        )
        def metric_by_segment(
            metric: Annotated[
                str, Field(description="first_response_minutes, followups_count or price_quoted")
            ],
            by: DimensionName,
            month: OptionalMonth = None,
        ) -> dict:
            return analytics.metric_by_segment(ds, metric, by, month)

        @self.add("data", "Find the date where the daily conversion rate shifted, if any.")
        def detect_changepoint() -> dict:
            return analytics.detect_changepoint(ds) or {"changepoint": None}

        @self.add("data", "Feature importance and accuracy of the conversion model trained on this dataset.")
        def model_drivers() -> dict:
            return model.card

        @self.add(
            "conversations",
            "How often each theme appears in customer messages, among lost and won leads and across two months.",
        )
        def conversation_themes(current: OptionalMonth = None, baseline: OptionalMonth = None) -> dict:
            return analytics.conversation_themes(ds, current, baseline)

        @self.add(
            "conversations",
            "Search customer messages for words or phrases, in the customers' own language. Returns a count and quotes.",
        )
        def search_conversations(
            query: Annotated[str, Field(description="Comma-separated words or phrases; any match counts")],
            status: Annotated[str | None, Field(description="won or lost")] = None,
            month: OptionalMonth = None,
            limit: Annotated[int, Field(ge=1, le=20)] = 5,
        ) -> dict:
            return analytics.search_conversations(ds, query, status, month, limit)

        @self.add("conversations", "Full message history for one lead.")
        def get_conversation(lead_id: str) -> dict:
            return analytics.get_conversation(ds, lead_id)

        @self.add(
            "knowledge",
            "Search the company's playbooks, pricing rules and catalog. Write the query in the documents' language.",
        )
        def search_policies(query: str, k: Annotated[int, Field(ge=1, le=6)] = 3) -> dict:
            return {"query": query, "results": index.search(query, k)}

        @self.add("records", "One lead with all of its attributes.")
        def get_lead(lead_id: str) -> dict:
            rows = ds.leads[ds.leads.lead_id == lead_id]
            if rows.empty:
                raise DatasetError(f"Lead {lead_id} not found")
            return json.loads(rows.drop(columns=["day"]).iloc[0].to_json(date_format="iso"))

        @self.add("records", "Orders placed by a customer or attached to a lead.")
        def get_orders(customer_id: str | None = None, lead_id: str | None = None) -> dict:
            if not customer_id and not lead_id:
                raise DatasetError("Provide customer_id or lead_id")
            orders = ds.orders
            if orders.empty:
                return {"orders": []}
            if customer_id:
                orders = orders[orders.customer_id == customer_id]
            if lead_id:
                orders = orders[orders.lead_id == lead_id]
            return {"orders": json.loads(orders.to_json(orient="records"))}

        @self.add("records", "Customer profile by customer id.")
        def get_customer(customer_id: str) -> dict:
            rows = (
                ds.customers[ds.customers.customer_id == customer_id]
                if not ds.customers.empty
                else ds.customers
            )
            if rows.empty:
                raise DatasetError(f"Customer {customer_id} not found")
            return json.loads(rows.iloc[0].to_json())
