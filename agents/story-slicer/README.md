# story slicer

Story slicer reads refined product intentions and configurations from a YAML file, breaking them down into atomic, independent, and valuable user stories, ensuring strict adherence to the INVEST criteria, Gherkin acceptance criteria (Given-When-Then), and deterministic Pydantic schemas.


## Architecture

The package uses ports and adapters to keep the refinement workflow separate from model SDKs and file handling:

| Hexagonal role | Current module | Responsibility |
