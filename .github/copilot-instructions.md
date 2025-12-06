# Coding
## Comments
- Don't use comments to express the content of code sections.
- Use comments only to explain technical complex code snippets. E.g. complex slicing of arrays, calls to functions, where the parameters are not easily visible or trickery with tensor dimensions.
- Only comment implementation details for heavy to read code.
- Avoid obvious comments that do not add value.
- After aggregation functions or other transformations, explain the shape and content of the output as well as the input dimensions that were expected and their meaning. Add these comments at the end of the corresponding line.

## Imports
- always import at the top of the file.

## Packages
- Always use conda to install packages.
- In case packages are needed, add them to the environment.yml file.
- Prefer using packages from conda repo over pip.
- Use pip packages if conda packages are not available.
- Pip packages are also added to the requirements.txt file.
- To install the packages update the environment.yml file and run `conda env update --file environment.yml`.

# Texting
- In LaTeX and Markdown only write one sentence per line.
- Every sentence starts a new line.
