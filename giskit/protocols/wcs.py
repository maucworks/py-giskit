"""WCS (Web Coverage Service) protocol implementation.

Supports downloading raster coverage data from WCS services.
Specification: https://www.ogc.org/standards/wcs
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from giskit.protocols.base import Protocol


class WCSError(Exception):
    """Raised when WCS requests fail."""

    pass


class WCSProtocol(Protocol):
    """WCS protocol implementation for coverage/raster data downloads.

    Features:
    - GetCapabilities and DescribeCoverage support
    - GetCoverage with bbox and resolution
    - GeoTIFF output format
    - Coordinate system transformation (planned)
    - Support for elevation data (DTM, DSM)
    """

    def __init__(
        self,
        base_url: str,
        coverage_id: str,
        version: str = "1.0.0",
        timeout: float = 120.0,
        native_crs: str = "EPSG:28992",
        native_resolution: Optional[float] = None,
        **kwargs: Any,
    ):
        """Initialize WCS protocol.

        Args:
            base_url: Base URL for WCS service
            coverage_id: Coverage identifier (e.g., "dsm_05m", "dtm_05m")
            version: WCS version (default: "1.0.0")
            timeout: Request timeout in seconds (longer for large rasters)
            native_crs: Native CRS of the coverage
            native_resolution: Native resolution in meters (if known)
            **kwargs: Additional configuration
        """
        super().__init__(base_url, timeout=timeout, **kwargs)
        self.coverage_id = coverage_id
        self.version = version
        self.native_crs = native_crs
        self.native_resolution = native_resolution

        # Coverage metadata (loaded lazily)
        self._metadata: Optional[dict[str, Any]] = None

    def _build_url(self, request: str, params: dict[str, Any]) -> str:
        """Build WCS request URL.

        Args:
            request: WCS request type (GetCapabilities, DescribeCoverage, GetCoverage)
            params: Request parameters

        Returns:
            Complete request URL
        """
        # Base parameters
        base_params = {
            "service": "WCS",
            "version": self.version,
            "request": request,
        }

        # Merge with request-specific params
        all_params = {**base_params, **params}

        # Build URL
        query_string = urlencode(all_params)
        return f"{self.base_url}?{query_string}"

    async def get_capabilities(self) -> dict[str, Any]:
        """Get WCS service capabilities.

        Returns:
            Dictionary with service metadata
        """
        client = await self._get_client()
        url = self._build_url("GetCapabilities", {})

        try:
            response = await client.get(url)
            response.raise_for_status()

            # Parse XML response
            root = ET.fromstring(response.content)

            # Extract coverage offerings
            # Note: Simplified parsing - may need enhancement for different WCS versions
            coverages = []
            for coverage in root.findall(".//{http://www.opengis.net/wcs}CoverageOfferingBrief"):
                name_elem = coverage.find("{http://www.opengis.net/wcs}name")
                if name_elem is not None:
                    coverages.append(name_elem.text)

            return {
                "title": "WCS Service",
                "version": self.version,
                "coverages": coverages,
                "base_url": self.base_url,
            }

        except httpx.HTTPError as e:
            raise WCSError(f"Failed to get capabilities: {e}") from e

    async def describe_coverage(self) -> dict[str, Any]:
        """Describe coverage metadata.

        Returns:
            Dictionary with coverage metadata (bbox, CRS, resolution, etc.)
        """
        if self._metadata is not None:
            return self._metadata

        client = await self._get_client()
        url = self._build_url("DescribeCoverage", {"coverage": self.coverage_id})

        try:
            response = await client.get(url)
            response.raise_for_status()

            # Parse XML response
            root = ET.fromstring(response.content)

            # Extract metadata (simplified - WCS 1.0.0 format)
            # Note: Different WCS versions have different XML schemas
            metadata = {
                "coverage_id": self.coverage_id,
                "version": self.version,
                "native_crs": self.native_crs,
                "native_resolution": self.native_resolution,
            }

            # Try to extract bbox from lonLatEnvelope
            envelope = root.find(".//{http://www.opengis.net/wcs}lonLatEnvelope")
            if envelope is not None:
                pos_elem = envelope.find("{http://www.opengis.net/gml}pos")
                if pos_elem is not None and pos_elem.text:
                    coords = pos_elem.text.split()
                    if len(coords) >= 4:
                        metadata["bbox_latlon"] = [
                            float(coords[0]),
                            float(coords[1]),
                            float(coords[2]),
                            float(coords[3]),
                        ]

            self._metadata = metadata
            return metadata

        except httpx.HTTPError as e:
            raise WCSError(f"Failed to describe coverage: {e}") from e

    async def get_features(
        self,
        bbox: tuple[float, float, float, float],
        layers: Optional[list[str]] = None,
        crs: str = "EPSG:4326",
        limit: Optional[int] = None,
        **kwargs: Any,
    ):
        """WCS does not support vector features.

        Raises:
            NotImplementedError: WCS is raster-only
        """
        raise NotImplementedError(
            "WCS protocol does not support vector features. " "Use get_coverage() for raster data."
        )

    async def get_coverage(
        self,
        bbox: tuple[float, float, float, float],
        product: str,
        resolution: float,
        crs: str = "EPSG:28992",
        output_format: str = "image/tiff",
        progress_callback: Optional[Any] = None,
        **kwargs: Any,
    ) -> np.ndarray:
        """Download coverage data for bounding box.

        Args:
            bbox: Bounding box (minx, miny, maxx, maxy) in request CRS
            product: Product/coverage name (ignored - uses configured coverage_id)
            resolution: Target resolution in meters
            crs: Coordinate reference system
            output_format: Output format (default: "image/tiff")
            progress_callback: Optional callback(message, percent)
            **kwargs: Additional parameters

        Returns:
            NumPy array with elevation/coverage data
        """
        self.validate_bbox(bbox)
        minx, miny, maxx, maxy = bbox

        # Validate CRS
        if crs != self.native_crs:
            raise ValueError(
                f"CRS {crs} does not match native CRS {self.native_crs}. "
                "Coordinate transformation not yet implemented."
            )

        if progress_callback:
            progress_callback(f"Requesting coverage: {self.coverage_id}", 0.0)

        # Calculate grid size based on resolution
        width_m = maxx - minx
        height_m = maxy - miny
        width_px = int(width_m / resolution)
        height_px = int(height_m / resolution)

        if progress_callback:
            progress_callback(
                f"Grid size: {width_px}x{height_px} pixels at {resolution}m resolution", 0.1
            )

        # Build GetCoverage request
        params = {
            "coverage": self.coverage_id,
            "crs": crs,
            "bbox": f"{minx},{miny},{maxx},{maxy}",
            "width": str(width_px),
            "height": str(height_px),
            "format": output_format,
        }

        url = self._build_url("GetCoverage", params)

        if progress_callback:
            progress_callback("Downloading coverage data...", 0.2)

        # Download coverage
        client = await self._get_client()

        try:
            response = await client.get(url)
            response.raise_for_status()

            if progress_callback:
                size_mb = len(response.content) / (1024 * 1024)
                progress_callback(f"Downloaded {size_mb:.2f} MB", 0.7)

            # Check if response is an error (XML) instead of raster
            content_type = response.headers.get("content-type", "")
            if "xml" in content_type.lower():
                # Try to parse error message
                try:
                    root = ET.fromstring(response.content)
                    error_msg = root.text or "Unknown WCS error"
                    raise WCSError(f"WCS service error: {error_msg}")
                except ET.ParseError:
                    raise WCSError("WCS service returned XML error (parse failed)")

            # Parse GeoTIFF using rasterio
            if progress_callback:
                progress_callback("Parsing GeoTIFF data...", 0.8)

            with MemoryFile(response.content) as memfile:
                with memfile.open() as dataset:
                    # Read first band (elevation data is typically single-band)
                    data = dataset.read(1)

                    # Get metadata

                    if progress_callback:
                        progress_callback(
                            f"Loaded {data.shape[0]}x{data.shape[1]} elevation grid", 0.9
                        )

            return data

        except httpx.HTTPError as e:
            raise WCSError(f"Failed to download coverage: {e}") from e

    async def save_coverage_as_geotiff(
        self,
        bbox: tuple[float, float, float, float],
        output_path: Path,
        resolution: float,
        crs: str = "EPSG:28992",
        progress_callback: Optional[Any] = None,
        **kwargs: Any,
    ) -> Path:
        """Download coverage and save as GeoTIFF file.

        Args:
            bbox: Bounding box (minx, miny, maxx, maxy)
            output_path: Path to save GeoTIFF
            resolution: Target resolution in meters
            crs: Coordinate reference system
            progress_callback: Optional callback(message, percent)
            **kwargs: Additional parameters

        Returns:
            Path to saved GeoTIFF
        """
        # Download coverage data
        data = await self.get_coverage(
            bbox=bbox,
            product=self.coverage_id,
            resolution=resolution,
            crs=crs,
            progress_callback=progress_callback,
            **kwargs,
        )

        if progress_callback:
            progress_callback("Saving GeoTIFF...", 0.95)

        # Create output directory if needed
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Calculate transform
        minx, miny, maxx, maxy = bbox
        transform = from_bounds(minx, miny, maxx, maxy, data.shape[1], data.shape[0])

        # Save as GeoTIFF
        with rasterio.open(
            output_path,
            "w",
            driver="GTiff",
            height=data.shape[0],
            width=data.shape[1],
            count=1,
            dtype=data.dtype,
            crs=crs,
            transform=transform,
            compress="lzw",
        ) as dst:
            dst.write(data, 1)

        if progress_callback:
            progress_callback(f"Saved to {output_path.name}", 1.0)

        return output_path


# Register protocol factory
def _create_wcs_protocol(config: dict[str, Any]) -> "WCSProtocol":
    """Factory function for creating WCS protocol instances.

    Args:
        config: Configuration dictionary with keys:
            - url: Base URL for the WCS service
            - coverage_id: Coverage identifier (required)
            - native_crs: Native CRS of the coverage (optional, default: EPSG:28992)
            - native_resolution: Native resolution in meters (optional)

    Returns:
        WCSProtocol instance

    Raises:
        ValueError: If required 'coverage_id' parameter is missing
    """
    url = config.get("url", "")
    coverage_id = config.get("coverage_id")

    if not coverage_id:
        raise ValueError("WCS protocol requires 'coverage_id' parameter in config")

    native_crs = config.get("native_crs", "EPSG:28992")
    native_resolution = config.get("native_resolution")

    return WCSProtocol(
        base_url=url,
        coverage_id=coverage_id,
        native_crs=native_crs,
        native_resolution=native_resolution,
    )


# Register with global registry
from giskit.protocols.registry import register_protocol

register_protocol("wcs", _create_wcs_protocol)
