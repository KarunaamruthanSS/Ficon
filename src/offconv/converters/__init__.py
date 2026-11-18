"""Converter modules.

Importing a module registers its converters. To add a new family of
formats (audio, video, ...), create a module here and import it below.
"""

from offconv.converters import documents, images  # noqa: F401
