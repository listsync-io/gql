#!/usr/bin/env python
import click
import glob
import subprocess
import time
import os
from os.path import join as join_paths, isfile, dirname, basename, splitext

from collections import defaultdict
from graphql import GraphQLSchema
from watchdog.observers import Observer
from watchdog.events import (
    FileSystemEventHandler,
    EVENT_TYPE_CREATED,
    EVENT_TYPE_MODIFIED,
)

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
        schema=schema, endpoint=endpoint, documents=join_paths(root, "**/*.graphql")
    )

    config.save(config_filename)

    click.echo(
        f"Config file generated at {click.style(config_filename, fg='bright_white')}\n\n"
    )


def process_files_with_same_domain(
    filenames: list, parser: QueryParser, renderer: DataclassesRenderer
):
    grouped_files = defaultdict(list)
    for filename in filenames:
        directory = dirname(filename)
        base_name = basename(filename)
        domain_name = base_name.split(".")[0]
        grouped_files[(directory, domain_name)].append(filename)

    class_names = []
    for (directory, domain_name), files in grouped_files.items():
        class_name = process_files_in_directory(
            directory, domain_name, files, parser, renderer
        )
        class_names.append(class_name)

    # Create __init__.py in each directory
    directories = set(directory for directory, _ in grouped_files.keys())
    for directory in directories:
        create_init_file(directory, class_names)


def process_files_in_directory(
    directory: str,
    domain_name: str,
    filenames: list,
    parser: QueryParser,
    renderer: DataclassesRenderer,
):
    buffer = []
    class_name = (
        f"{dirname(directory).split('/')[-1].capitalize()}{domain_name.capitalize()}"
    )
    output_file = join_paths(directory, f"{class_name}.py")

    buffer.append(renderer.render_shared_code())
    buffer.append(f"\n\nclass {class_name}:\n")

    for filename in filenames:
        click.echo(f"Parsing {filename} ... ", nl=False)
        with open(filename, "r") as fin:
            query = fin.read()
            try:
                parsed = parser.parse(query)
                rendered = renderer.render(parsed, basename(filename).split(".")[1])
                buffer.append(f"    # From {basename(filename)}\n")
                buffer.append("    " + rendered.replace("\n", "\n    "))
                buffer.append("\n")
                click.secho("Success!", fg="bright_white")
            except AnonymousQueryError:
                click.secho("Failed!", fg="bright_red")
                click.secho("\tQuery is missing a name", fg="bright_black")
            except InvalidQueryError as invalid_err:
                click.secho("Failed!", fg="bright_red")
                click.secho(f"\t{invalid_err}", fg="bright_black")

    if len(buffer) > 2:  # If there are valid parsed contents
        # Write all rendered content to the output file
        with open(output_file, "w") as outfile:
            for chunk in buffer:
                outfile.write(chunk)
                outfile.write("\n")

        # Format the output file using Black
        format_with_black(output_file)

    return class_name


def create_init_file(directory: str, class_names: list):
    init_file_path = join_paths(directory, "__init__.py")
    with open(init_file_path, "w") as init_file:
        for class_name in class_names:
            init_file.write(f"from .{class_name} import {class_name}\n")


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
