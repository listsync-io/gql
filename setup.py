from setuptools import setup, find_packages

setup(
    name="gql-compiler",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        "click",
        "GraphQL-core-next",
        "watchdog",
        "requests",
        "aiohttp",
    ],
    # Additional metadata
    author="Your Name",
    author_email="your.email@example.com",
    description="Description of your package",
)
