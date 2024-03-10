from setuptools import setup, find_packages

setup(
    name="gql",
    version="1.0",
    packages=find_packages(),
    package_dir={"": "."},
    install_requires=[
        "click",
        "GraphQL-core-next",
        "watchdog",
        "requests",
        "aiohttp",
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
