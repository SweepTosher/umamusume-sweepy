from sweepy.brain_client import BrainAPIError, BrainClient
from sweepy.catalog import Catalog
from sweepy.config import RuntimeConfig
from sweepy.macro_runner import MacroCareerRunner
from sweepy.qr_svg import encode_qr_matrix, render_qr_svg
from sweepy.race_binary import decode_player_rank
from sweepy.stripper import strip_career_state
from sweepy.webui import SweepyAppState, SweepyWebServer

__version__ = "2.0.0"

__all__ = [
    "__version__",
    "BrainAPIError",
    "BrainClient",
    "Catalog",
    "MacroCareerRunner",
    "RuntimeConfig",
    "SweepyAppState",
    "SweepyWebServer",
    "decode_player_rank",
    "encode_qr_matrix",
    "render_qr_svg",
    "strip_career_state",
]
