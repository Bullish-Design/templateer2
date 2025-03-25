from pydantic import BaseModel, Field
from typing import List, Optional


class Person(BaseModel):
    """Represents a person with personal information."""

    name: str
    age: int
    email: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    location: str


# /// template
# output-file = "person_schema.md"
# imports = ["helpers.py"]
# reference-file = "./data/sample.json"
# ///
"""
# Person Schema Documentation

## Class: Person

{{ pydantic_docs["Person"] }}

### Fields:
{% for field_name, field in pydantic_fields["Person"].items() %}

#### {{ field_name }}
{%- set type_str = field.annotation|string %}
{%- if type_str.startswith("<class") %}
    {%- set type_str = type_str | regex_replace("^<class\\s*'([^']+)'\\s*>$", "\\1") %}
{%- endif %}
{%- if type_str.startswith("typing.Optional[") or type_str.startswith("Optional[") %}
    {%- set type_str = type_str | regex_replace("^(?:typing\\.)?Optional\\[(.*)\\]$", "\\1") %}
{%- endif %}
{%- set type_str = type_str | regex_replace("typing\\.", "") %}
- **Type:** {{ type_str }}
{%- if "Optional" in field.annotation|string %}
- Optional=True
{%- endif %}
{%- if "List" in field.annotation|string %}
- List=True
{%- endif %}
{%- endfor %}

### Schema:

```json
{{ get_schema_json(Person) }}
```
"""
