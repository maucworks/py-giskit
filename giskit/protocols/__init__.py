"""Protocol implementations for different spatial data APIs.

Protocols define how to communicate with different API standards:
- OGC API Features (WFS 3.0)
- WMS/WMTS
- OGC Coverages
- GTFS (General Transit Feed Specification)
- Custom APIs

Each protocol can have provider-specific quirks configured.
"""

from giskit.protocols.base import Protocol
from giskit.protocols.csv import CSVProtocol
from giskit.protocols.gtfs import GTFSProtocol
from giskit.protocols.ogc_features import OGCFeaturesError, OGCFeaturesProtocol
from giskit.protocols.quirks import KNOWN_QUIRKS, ProtocolQuirks, get_quirks
from giskit.protocols.registry import create_protocol, get_registry, register_protocol

# Import protocol modules to trigger registration
# This ensures all protocols are registered when giskit.protocols is imported
from giskit.protocols import csv, gtfs, ogc_features, wcs, wfs, wmts

__all__ = [
    "Protocol",
    "CSVProtocol",
    "GTFSProtocol",
    "OGCFeaturesProtocol",
    "OGCFeaturesError",
    "ProtocolQuirks",
    "get_quirks",
    "KNOWN_QUIRKS",
    "register_protocol",
    "create_protocol",
    "get_registry",
]
