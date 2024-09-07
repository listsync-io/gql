#!/usr/bin/env python
import textwrap
import click
import glob
import subprocess
import time
import os
import pluralizer
import re

from os.path import join as join_paths, isfile, dirname, basename, splitext

from collections import defaultdict
from graphql import GraphQLSchema
from watchdog.observers import Observer
from watchdog.events import (
    FileSystemEventHandler,
    EVENT_TYPE_CREATED,
    EVENT_TYPE_MODIFIED,
)
from gql.utils_codegen import CodeChunk

from gql.config import Config
from gql.query_parser import QueryParser, AnonymousQueryError, InvalidQueryError
from gql.renderer_dataclasses import DataclassesRenderer
from gql.utils_schema import load_schema

DEFAULT_CONFIG_FNAME = ".gql.json"
SCHEMA_PROMPT = click.style("Where is your schema?: ", fg="bright_white") + click.style(
    "(path or url) ", fg="bright_black", dim=False
)

ROOT_PROMPT = click.style(
    "Whats the root of your project: ", fg="bright_white"
) + click.style("(path or url) ", fg="bright_black", dim=False)


def safe_remove(fname):
    try:
        os.remove(fname)
    except:
        pass


@click.group()
def cli():
    pass


@cli.command()
@click.option("--schema", prompt=SCHEMA_PROMPT, default="http://localhost:4000")
@click.option("--endpoint", prompt=SCHEMA_PROMPT, default="same as schema")
@click.option("--root", prompt=ROOT_PROMPT, default="./src")
@click.option(
    "-c",
    "--config",
    "config_filename",
    default=DEFAULT_CONFIG_FNAME,
    type=click.Path(exists=False),
)
def init(schema, endpoint, root, config_filename):
    if isfile(config_filename):
        click.confirm(
            f"{config_filename} already exists. Are you sure you want to continue?",
            abort=True,
        )

    if endpoint == "same as schema":
        endpoint = schema

    config = Config(
        schema=schema,
        endpoint=endpoint,
        documents=join_paths("queries", "**/*.graphql"),
    )

    config.save(config_filename)

    click.echo(
        f"Config file generated at {click.style(config_filename, fg='bright_white')}\n\n"
    )


def process_files_with_same_domain(
    filenames: list, parser: QueryParser, renderer: DataclassesRenderer
):
    def to_snake_case(camel_case_string):
        # Use regular expression to identify capital letters and add underscores before them
        snake_case_string = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", camel_case_string)
        # Convert the entire string to lowercase
        return snake_case_string.lower()

    grouped_files = {
        "app": {},
        "packages": {},
    }
    for filename in filenames:
        parts = filename.split("/")

        del parts[0]

        name_of_the_file = parts[-1]
        app_or_package = parts[0]

        name_of_the_model = ""
        if app_or_package == "app":
            name_of_the_model = parts[2]
        elif app_or_package == "packages":
            name_of_the_model = parts[1]

        if name_of_the_model not in grouped_files[app_or_package]:
            grouped_files[app_or_package][name_of_the_model] = []

        grouped_files[app_or_package][name_of_the_model].append(
            {
                "full_path": filename,
                "name_of_the_file": name_of_the_file,
                "name_of_the_function": to_snake_case(
                    name_of_the_file.split(".graphql")[0]
                ),
                "app_or_package": app_or_package,
                "name_of_the_model": name_of_the_model,
            }
        )

    packages_data = {}
    for key, items in grouped_files["packages"].items():
        for item in items:
            needle = item["full_path"].split("/")[4]

            if needle not in packages_data:
                packages_data[needle] = []

            packages_data[needle].append(item)
        grouped_files["packages"][key] = packages_data

    gathered_data = {}

    for key, models in grouped_files["app"].items():
        for item in models:
            filename, function = process_files_in_directory(
                full_path=item["full_path"],
                name_of_the_file=item["name_of_the_file"],
                app_or_package=item["app_or_package"],
                name_of_the_function=item["name_of_the_function"],
                name_of_the_model=item["name_of_the_model"],
                parser=parser,
                renderer=renderer,
            )

            if key not in gathered_data:
                gathered_data[key] = {
                    "domain_type": "app",
                    "path": os.path.normpath(os.path.join(item["full_path"], "../..")),
                    "functions": [],
                }

            gathered_data[key]["functions"].append(
                {
                    "filename": filename,
                    "function": function,
                }
            )

    for parent_name, boks in grouped_files["packages"].items():
        for key, items in boks.items():
            for item in items:
                filename, function = process_files_in_directory(
                    full_path=item["full_path"],
                    name_of_the_file=item["name_of_the_file"],
                    app_or_package=item["app_or_package"],
                    name_of_the_function=item["name_of_the_function"],
                    name_of_the_model=item["name_of_the_model"],
                    parser=parser,
                    renderer=renderer,
                )

                if parent_name + key not in gathered_data:
                    gathered_data[parent_name + key] = {
                        "domain_type": "packages",
                        "actual_name": key,
                        "path": os.path.normpath(
                            os.path.join(item["full_path"], "../..")
                        ),
                        "functions": [],
                    }

                gathered_data[parent_name + key]["functions"].append(
                    {
                        "filename": filename,
                        "function": function,
                    }
                )

    for name_of_the_model, item in gathered_data.items():
        create_init_file(
            name_of_the_model=name_of_the_model,
            directory=item["path"],
            functions=item["functions"],
            domain_type=item["domain_type"],
            actual_name=item.get("actual_name", None),
        )


def create_init_file(
    name_of_the_model: str,
    directory: str,
    functions: list,
    domain_type: str,
    actual_name: str = None,
):
    init_file_path = os.path.join(directory, "__init__.py")

    # List all files in the directory
    files_in_directory = os.listdir(directory)

    # Create or overwrite the __init__.py file
    with open(init_file_path, "w") as init_file:
        init_file.write("# pyright: reportUnusedImport=false\n")

        # Include additional functions specified in the functions list
        for item in functions:
            init_file.write(
                f"from .executor.{item['filename']} import {item['function']}\n"
            )

        # Automatically include files at the same level
        for file_name in files_in_directory:
            if file_name.endswith(".py") and file_name != "__init__.py":
                class_name = os.path.splitext(file_name)[0]
                init_file.write(f"from .{class_name} import {class_name}\n")


def process_files_in_directory(
    full_path: str,
    name_of_the_file: str,
    app_or_package: str,
    name_of_the_model: str,
    name_of_the_function: str,
    parser: QueryParser,
    renderer: DataclassesRenderer,
):
    bare_file_name = "_".join(name_of_the_file.split(".")[:-1])
    verb = name_of_the_function.split("_")[0]

    domain_name = re.sub(r"(?<!^)(?=[A-Z])", "_", name_of_the_model).lower()

    start_path = os.path.normpath(os.path.join(full_path, "../.."))
    output_file = f"{start_path}/executor/{bare_file_name}.py"

    buffer = CodeChunk()
    buffer.write(renderer.render_shared_code())

    click.echo(f"Parsing {full_path} ... ", nl=False)

    with open(full_path, "r") as fin:
        query = fin.read()
        try:
            parsed = parser.parse(query)
            rendered = renderer.render(parsed, full_path, verb)

            with buffer.write_block("def {}():".format(name_of_the_function)):
                buffer.write("return {}, '{}'".format(verb, parsed.objects[0].name))

            buffer.write(f"class {verb}:")
            buffer.write("    " + rendered.replace("\n", "\n    "))
            click.secho("Success!", fg="bright_white")
        except AnonymousQueryError:
            click.secho("Failed!", fg="bright_red")
            click.secho("\tQuery is missing a name", fg="bright_black")
        except InvalidQueryError as invalid_err:
            click.secho("Failed!", fg="bright_red")
            click.secho(f"\t{invalid_err}", fg="bright_black")

    if len(buffer.lines) > 2:
        os.makedirs(dirname(output_file), exist_ok=True)
        with open(output_file, "w") as outfile:
            for chunk in buffer.lines:
                outfile.write(chunk)
                outfile.write("\n")

        # Format the output file using Black
        format_with_black(output_file)

    return bare_file_name, name_of_the_function


@cli.command()
@click.option(
    "-c",
    "--config",
    "config_filename",
    default=DEFAULT_CONFIG_FNAME,
    type=click.Path(exists=True),
)
def run(config_filename):
    if not isfile(config_filename):
        click.echo(f"Could not find configuration file {config_filename}")

    config = Config.load(config_filename)
    schema = load_schema(config.schema)

    filenames = glob.glob(config.documents, recursive=True)

    query_parser = QueryParser(schema)
    query_renderer = DataclassesRenderer(schema, config)

    process_files_with_same_domain(filenames, query_parser, query_renderer)


def format_with_black(filename):
    """Format a Python file using Black."""
    try:
        subprocess.run(["black", filename], check=True)
        click.echo(f"Formatted {filename} with Black.")
    except subprocess.CalledProcessError as e:
        click.echo(f"Error formatting {filename} with Black: {e}")


@cli.command()
@click.option(
    "-c",
    "--config",
    "config_filename",
    default=DEFAULT_CONFIG_FNAME,
    type=click.Path(exists=True),
)
def watch(config_filename):
    class Handler(FileSystemEventHandler):
        def __init__(self, config: Config, schema: GraphQLSchema):
            self.parser = QueryParser(schema)
            self.renderer = DataclassesRenderer(schema, config)

        def on_any_event(self, event):
            if event.is_directory:
                return

            if event.event_type in {EVENT_TYPE_CREATED, EVENT_TYPE_MODIFIED}:
                filenames = [
                    os.path.abspath(fn)
                    for fn in glob.iglob(config.documents, recursive=True)
                ]
                if event.src_path not in filenames:
                    return

                process_files_with_same_domain(filenames, self.parser, self.renderer)

    if not isfile(config_filename):
        click.echo(f"Could not find configuration file {config_filename}")

    config = Config.load(config_filename)
    schema = load_schema(config.schema)

    click.secho(f"Watching {config.documents}", fg="cyan")
    click.secho("Ready for changes...", fg="cyan")

    observer = Observer()
    observer.schedule(Handler(config, schema), os.path.abspath("./"), recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(5)
    except:
        observer.stop()
        print("Error")

    observer.join()


if __name__ == "__main__":
    cli()
