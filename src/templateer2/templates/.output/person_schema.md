# Person Schema Documentation

## Class: Person

Represents a person with personal information.

### Fields:


#### name
- **Type:** str

#### age
- **Type:** int

#### email
- **Type:** str
- Optional=True

#### tags
- **Type:** List[str]
- List=True

#### location
- **Type:** str

### Schema:

```json
{
  "description": "Represents a person with personal information.",
  "properties": {
    "name": {
      "title": "Name",
      "type": "string"
    },
    "age": {
      "title": "Age",
      "type": "integer"
    },
    "email": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Email"
    },
    "tags": {
      "items": {
        "type": "string"
      },
      "title": "Tags",
      "type": "array"
    },
    "location": {
      "title": "Location",
      "type": "string"
    }
  },
  "required": [
    "name",
    "age",
    "location"
  ],
  "title": "Person",
  "type": "object"
}
```