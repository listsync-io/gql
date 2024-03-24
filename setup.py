from setuptools import setup

setup(
    name="cfk_gql",
    version="3.0",
    packages=["gql", "gql.clients"],
    package_data={"": ["*"]},
    package_dir={"": "."},
    install_requires=[
        "click",
        "GraphQL-core-next",
        "watchdog",
        "requests",
        "aiohttp",
        "dataclasses_json",
    ],
    entry_points={
        "console_scripts": [
            "gql = gql.cli:cli",
        ],
    },
    # Additional metadata
    author="Lio",
    author_email="lio@example.com",
)
