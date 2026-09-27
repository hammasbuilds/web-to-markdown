"""web2md: turn a web page into clean, agent-ready markdown with the standard library."""

__version__ = "0.1.0"

from web2md.convert import Conversion, convert  # noqa: E402
from web2md.extract import ExtractOptions  # noqa: E402
from web2md.metadata import Metadata  # noqa: E402

__all__ = ["Conversion", "ExtractOptions", "Metadata", "__version__", "convert"]
