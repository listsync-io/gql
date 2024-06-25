from graphql import GraphQLSchema

from gql.config import Config
from gql.utils_codegen import CodeChunk
from gql.query_parser import (
    ParsedQuery,
    ParsedField,
    ParsedObject,
    ParsedEnum,
    ParsedOperation,
    ParsedVariableDefinition,
)

from typing import Optional, Dict, Any


class DataclassesRenderer:

    def __init__(self, schema: GraphQLSchema, config: Config):
        self.schema = schema
        self.config = config

    def render(self, parsed_query: ParsedQuery):
        # We sort fragment nodes to be first and operations to be last because of dependecies
        buffer = CodeChunk()
        buffer.write("# AUTOGENERATED file. Do not Change!")
        buffer.write("import re")
        buffer.write("from functools import partial")
        buffer.write("from typing import Any, Callable, Mapping, List")
        buffer.write("from enum import Enum")
        buffer.write("from dataclasses import dataclass, field")
        buffer.write("from dataclasses_json import dataclass_json")
        buffer.write("from gql.clients import Client, AsyncIOClient")
        buffer.write("from gql.renderer_dataclasses import DataclassesRenderer")
        buffer.write("from app.facades import auth")
        buffer.write("from dateutil import parser")
        buffer.write("from app.exceptions import CantProceed")
        buffer.write("")

        if self.config.custom_header:
            buffer.write_lines(self.config.custom_header.split("\n"))

        buffer.write("")

        self.__render_datetime_field(buffer)

        # Enums
        if parsed_query.enums:
            self.__render_enum_field(buffer)
            for enum in parsed_query.enums:
                self.__render_enum(buffer, enum)

        sorted_objects = sorted(
            parsed_query.objects,
            key=lambda obj: 1 if isinstance(obj, ParsedOperation) else 0,
        )
        for obj in sorted_objects:
            if isinstance(obj, ParsedObject):
                self.__render_object(parsed_query, buffer, obj)
            elif isinstance(obj, ParsedOperation):
                self.__render_operation(parsed_query, buffer, obj)

        return str(buffer)

    @staticmethod
    def __render_enum_field(buffer: CodeChunk):
        with buffer.write_block("def enum_field(enum_type):"):
            with buffer.write_block("def encode_enum(value):"):
                buffer.write("return value.value")
            buffer.write("")
            with buffer.write_block("def decode_enum(t, value):"):
                buffer.write("return t(value)")

            buffer.write("")
            buffer.write(
                "return field(metadata={'dataclasses_json': {'encoder': encode_enum, 'decoder': partial(decode_enum, enum_type)}})"
            )
            buffer.write("")

    @staticmethod
    def __render_datetime_field(buffer: CodeChunk):
        buffer.write("")
        buffer.write("from datetime import datetime")
        buffer.write("from marshmallow import fields as marshmallow_fields")

        buffer.write("def custom_datetime_encoder(dt):")
        buffer.write("    return dt.isoformat() if dt is not None else None")
        buffer.write(
            "DATETIME_FIELD = field(metadata={'dataclasses_json': {'encoder': custom_datetime_encoder, 'decoder': parser.parse, 'mm_field': marshmallow_fields.DateTime(format='iso')}})"
        )
        buffer.write("")

    def __render_object(
        self, parsed_query: ParsedQuery, buffer: CodeChunk, obj: ParsedObject
    ):
        class_parents = "" if not obj.parents else f'({", ".join(obj.parents)})'

        buffer.write("@dataclass_json")
        buffer.write("@dataclass")
        with buffer.write_block(f"class {obj.name}{class_parents}:"):
            # render child objects
            for child_object in obj.children:
                self.__render_object(parsed_query, buffer, child_object)

            # render fields
            sorted_fields = sorted(
                obj.fields, key=lambda f: (f.type != "DateTime", f.nullable)
            )
            for field in sorted_fields:
                self.__render_field(parsed_query, buffer, field)

            # pass if not children or fields
            if not (obj.children or obj.fields):
                buffer.write("pass")

        buffer.write("")

    @staticmethod
    def simplify(response: Dict[str, Any], operation_name: str) -> Dict[str, Any]:
        if "data" not in response or ("errors" in response and response["errors"]):
            return response  # Return as-is in case of errors or missing data

        # if operation_name is store, make it insert
        operation_name = operation_name.replace("store", "insert")
        operation_name = operation_name.replace("destroy", "delete")

        data = response["data"]
        base_key = operation_name
        item_key = f"{base_key}"

        if f"{item_key}_by_pk" in data:
            if data[f"{item_key}_by_pk"] is None:
                return {}

            data = {**data, **data[f"{item_key}_by_pk"]}
            data.pop(f"{item_key}_by_pk")

            return data

        return data.get(item_key, [])

    @staticmethod
    def relayify(response: Dict[str, Any], operation_name: str) -> Dict[str, Any]:
        """
        Transforms a standard GraphQL response into a Relay-style response.
        Dynamically handles based on operation_name extracted from class name or passed explicitly.
        """
        if "data" not in response or ("errors" in response and response["errors"]):
            return response  # Return as-is in case of errors or missing data

        # if operation_name is store, make it insert
        operation_name = operation_name.replace("store", "insert")
        operation_name = operation_name.replace("destroy", "delete")

        data = response["data"]
        base_key = operation_name  # Adjust this if you need to extract from class name or metadata
        item_key = f"{base_key}"  # Adjust according to your data structure, e.g., for `amazon_product` queries
        aggregate_key = f"{base_key}_aggregate"

        total_count = (
            data.get(aggregate_key, {}).get("aggregate", {}).get("count", None)
        )

        relay_response = {}

        if total_count is not None:
            relay_response["totalCount"] = total_count
            relay_response["pageInfo"] = {
                "hasNextPage": False,  # Placeholder, adjust based on your pagination logic
                "endCursor": None,  # Placeholder for cursor logic
            }
            if total_count > 0:
                edges = [
                    {
                        "cursor": str(index),  # Placeholder for cursor logic
                        "node": item,
                    }
                    for index, item in enumerate(data.get(item_key, []), start=1)
                ]
                relay_response["edges"] = edges
                return relay_response

        if f"{item_key}_by_pk" in data:
            data = {**data, **data[f"{item_key}_by_pk"]}
            data.pop(f"{item_key}_by_pk")

        # if response contains more than one item, return as-is
        if len(data) > 1:
            return data

        return data.get(item_key, [])

    def __render_operation(
        self, parsed_query: ParsedQuery, buffer: CodeChunk, parsed_op: ParsedOperation
    ):
        buffer.write("@dataclass_json")
        buffer.write("@dataclass")
        with buffer.write_block(f"class {parsed_op.name}:"):
            buffer.write('__QUERY__ = """')
            buffer.write(parsed_query.query)
            buffer.write('"""')
            buffer.write("")

            # Render children
            for child_object in parsed_op.children:
                self.__render_object(parsed_query, buffer, child_object)

            # operation fields
            buffer.write("")
            buffer.write(f"data: {parsed_op.name}Data = None")
            buffer.write("errors: Any = None")
            buffer.write("")

            # Execution functions
            vars_args_list = [f"{var.name}=None" for var in parsed_op.variables]
            vars_args_str = ", ".join(vars_args_list)
            if vars_args_str:
                vars_args_str += ", "

            variables_dict_lines = []
            for x in parsed_op.variables:
                defval = x.default_value
                if x.type == "str" and defval is None:
                    defval = '""'

                variables_dict_lines.append(
                    f"'{x.name}': {x.name} if {x.name} is not None else {defval}"
                )

            buffer.write("@classmethod")
            with buffer.write_block(
                f"def execute(cls, {vars_args_str}on_before_callback: Callable[[Mapping[str, str], Mapping[str, str]], None] = None):"
            ):
                buffer.write(f"client = Client('{self.config.endpoint}')")
                variables_dict_str = ", ".join(variables_dict_lines)
                buffer.write(f"variables = {{{variables_dict_str}}}")
                buffer.write(
                    "response_text = client.call(cls.__QUERY__, variables=variables, on_before_callback=on_before_callback)"
                )
                buffer.write("data = cls.from_json(response_text).to_dict()")

                buffer.write("if data.get('errors'):")
                buffer.write("    raise CantProceed(data['errors'])")

                buffer.write(
                    "operation_name = cls.__name__.replace('find', '').replace('get', '')"
                )
                buffer.write(
                    "singular_str = operation_name[:-1] if operation_name.endswith('s') else operation_name"
                )
                buffer.write(
                    "snake_case_str = re.sub(r'(?<!^)(?=[A-Z])', '_', singular_str).lower()"
                )

                buffer.write(
                    "return DataclassesRenderer.relayify(data, snake_case_str) if auth.is_standard_call() else DataclassesRenderer.simplify(data, snake_case_str)"
                )

            buffer.write("")

            buffer.write("@classmethod")
            with buffer.write_block(
                f"async def execute_async(cls, {vars_args_str}on_before_callback: Callable[[Mapping[str, str], Mapping[str, str]], None] = None):"
            ):
                buffer.write(f"client = AsyncIOClient('{self.config.endpoint}')")
                buffer.write(f"variables = {{{variables_dict_str}}}")
                buffer.write(
                    "response_text = await client.call(cls.__QUERY__, variables=variables, on_before_callback=on_before_callback)"
                )
                buffer.write("data = cls.from_json(response_text).to_dict()")

                buffer.write("if data.get('errors'):")
                buffer.write("    raise CantProceed(data['errors'])")

                buffer.write(
                    "operation_name = cls.__name__.replace('find', '').replace('get', '')"
                )
                buffer.write(
                    "singular_str = operation_name[:-1] if operation_name.endswith('s') else operation_name"
                )
                buffer.write(
                    "snake_case_str = re.sub(r'(?<!^)(?=[A-Z])', '_', singular_str).lower()"
                )

                buffer.write(
                    "return DataclassesRenderer.relayify(data, snake_case_str) if auth.is_standard_call() else DataclassesRenderer.simplify(data, snake_case_str)"
                )

            buffer.write("")
            buffer.write("")

    @staticmethod
    def __render_variable_definition(var: ParsedVariableDefinition):
        if not var.nullable:
            return f"{var.name}: {var.type}"

        return f'{var.name}: {var.type} = {var.default_value or "None"}'

    @staticmethod
    def __render_field(
        parsed_query: ParsedQuery, buffer: CodeChunk, field: ParsedField
    ):
        enum_names = [e.name for e in parsed_query.enums]
        is_enum = field.type in enum_names
        suffix = ""
        field_type = field.type

        if is_enum:
            suffix = f"= enum_field({field.type})"

        if field.nullable:
            suffix = f"= {field.default_value}"

        if field.type == "DateTime":
            suffix = "= DATETIME_FIELD"
            field_type = "datetime"

        if field_type in [
            "List[user_amazon_association]",
            "List[user_ebay_association]",
        ]:
            suffix = f"= {field.default_value}"

        buffer.write(f"{field.name}: {field_type} {suffix}")

    @staticmethod
    def __render_enum(buffer: CodeChunk, enum: ParsedEnum):
        with buffer.write_block(f"class {enum.name}(Enum):"):
            for value_name, value in enum.values.items():
                if isinstance(value, str):
                    value = f"'{value}'"

                buffer.write(f"{value_name} = {value}")

        buffer.write("")
