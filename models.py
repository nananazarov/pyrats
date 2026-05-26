"""
File: models.py
PYRATS — Data Models
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

ColType = Literal["string", "number", "boolean"]


class ColumnDef(BaseModel):
    name: str
    type: ColType = "string"


class RuleRow(BaseModel):
    id: str
    priority: int = 1
    conditions: List[str] = Field(default_factory=list)
    results: List[str] = Field(default_factory=list)
    annotation: str = ""
    stop_on_match: bool = True


class TableSchema(BaseModel):
    inputs: List[ColumnDef] = Field(default_factory=list)
    outputs: List[ColumnDef] = Field(default_factory=list)
    rules: List[RuleRow] = Field(default_factory=list)


class TriggerModel(BaseModel):
    path: str
    function_name: str
    description: Optional[str] = None
