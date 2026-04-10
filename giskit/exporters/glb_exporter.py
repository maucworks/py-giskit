"""GLB exporter using ifcopenshell.geom.

Converts IFC to GLB (glTF binary) format for web viewers.
Uses ifcopenshell.geom Python API for geometry extraction.

REQUIREMENTS:
    This module requires IfcOpenShell and pygltflib to be installed.

Installation:
    # Install giskit with IFC support
    pip install giskit[ifc]

    # Or install dependencies separately
    pip install ifcopenshell pygltflib
"""

import gzip
from pathlib import Path
from typing import Any, Dict, List, Tuple

import ifcopenshell
import ifcopenshell.geom
import numpy as np
import pygltflib


class GLBExporter:
    """Export IFC to GLB using ifcopenshell.geom."""

    def __init__(self):
        """Initialize GLB exporter."""
        pass

    def is_available(self) -> bool:
        """Check if required dependencies are available."""
        try:
            import ifcopenshell.geom  # noqa: F401
            import pygltflib  # noqa: F401

            return True
        except ImportError:
            return False

    def get_install_instructions(self) -> str:
        """Get installation instructions for current platform."""
        instructions = [
            "GLB export requires ifcopenshell and pygltflib:",
            "",
            "Install giskit with IFC support:",
            "  pip install giskit[ifc]",
            "",
            "Or install dependencies separately:",
            "  pip install ifcopenshell pygltflib",
        ]

        return "\n".join(instructions)

    def ifc_to_glb(
        self,
        ifc_path: Path,
        glb_path: Path,
        use_world_coords: bool = True,
        generate_uvs: bool = True,
        center_model: bool = False,
        compress: bool = True,
    ) -> None:
        """Convert IFC file to GLB using ifcopenshell.geom.

        Args:
            ifc_path: Input IFC file path
            glb_path: Output GLB file path
            use_world_coords: Use world coordinates (default: True)
            generate_uvs: Generate UV coordinates (default: True)
            center_model: Center model at origin (default: False)
            compress: Gzip compress output (default: True, adds .gz extension)

        Raises:
            RuntimeError: If dependencies are not available
            Exception: If conversion fails
        """
        if not self.is_available():
            raise RuntimeError(self.get_install_instructions())

        print(f"Converting IFC to GLB: {ifc_path} → {glb_path}")
        print("  Using ifcopenshell.geom")

        # Open IFC file
        ifc_file = ifcopenshell.open(str(ifc_path))

        # Configure geometry settings
        settings = ifcopenshell.geom.settings()
        settings.set("use-world-coords", use_world_coords)
        settings.set("weld-vertices", True)
        settings.set("generate-uvs", generate_uvs)

        # Extract geometry from IFC
        print("  Extracting geometry...")
        meshes, materials_map = self._extract_geometry(ifc_file, settings)

        if not meshes:
            raise RuntimeError("No geometry found in IFC file")

        print(f"  Extracted {len(meshes)} mesh(es)")
        print(f"  Found {len(materials_map)} unique material(s)")

        # Center model if requested
        if center_model:
            self._center_meshes(meshes)

        # Build GLB
        print("  Building GLB...")
        gltf = self._build_gltf(meshes, materials_map)

        # Write GLB file
        glb_path.parent.mkdir(parents=True, exist_ok=True)
        gltf.save(str(glb_path))

        print(f"✓ GLB export complete: {glb_path}")

        # Show file sizes
        if glb_path.exists():
            glb_mb = glb_path.stat().st_size / (1024 * 1024)
            print(f"  GLB size: {glb_mb:.1f} MB")

            # Compress if requested
            if compress:
                gz_path = Path(str(glb_path) + ".gz")
                with open(glb_path, "rb") as f_in:
                    with gzip.open(gz_path, "wb") as f_out:
                        f_out.writelines(f_in)

                if gz_path.exists():
                    gz_mb = gz_path.stat().st_size / (1024 * 1024)
                    ratio = (1 - gz_mb / glb_mb) * 100
                    print(f"  Compressed: {gz_mb:.1f} MB ({ratio:.0f}% reduction)")

    def _extract_geometry(
        self, ifc_file: Any, settings: Any
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        """Extract geometry from IFC file.

        Args:
            ifc_file: IFC file object
            settings: Geometry settings

        Returns:
            Tuple of (meshes, materials_map)
            - meshes: List of mesh dicts with vertices, indices, material_id
            - materials_map: Dict mapping material_id to color/properties
        """
        meshes: List[Dict[str, Any]] = []
        materials_map: Dict[str, Dict[str, Any]] = {}

        # Create geometry iterator
        iterator = ifcopenshell.geom.iterator(settings, ifc_file, num_threads=1)

        if iterator.initialize():
            while True:
                shape = iterator.get()
                # Get product by GUID (shape is a named tuple with guid attribute)
                product = ifc_file.by_guid(shape.guid)  # type: ignore

                # Get geometry (shape has a geometry attribute)
                geometry = shape.geometry  # type: ignore

                # Get vertices (flat array of floats: x1,y1,z1,x2,y2,z2,...)
                verts = geometry.verts  # type: ignore
                vertices = np.array(verts).reshape(-1, 3)

                # Get faces (flat array of ints: i1,i2,i3,i4,i5,i6,...)
                faces = geometry.faces  # type: ignore
                indices = np.array(faces, dtype=np.uint32)

                # Get material/color
                material_id = self._get_material_id(product, geometry)
                if material_id not in materials_map:
                    materials_map[material_id] = self._extract_material(product, geometry)

                # Store mesh
                meshes.append(
                    {
                        "vertices": vertices,
                        "indices": indices,
                        "material_id": material_id,
                        "name": product.Name or f"{product.is_a()}_{product.id()}",
                    }
                )

                if not iterator.next():
                    break

        return meshes, materials_map

    def _get_material_id(self, product: Any, geometry: Any) -> str:
        """Get material ID for a product."""
        # Try to get material from IFC
        if hasattr(product, "HasAssociations"):
            for association in product.HasAssociations:
                if association.is_a("IfcRelAssociatesMaterial"):
                    material = association.RelatingMaterial
                    if hasattr(material, "Name") and material.Name:
                        return f"mat_{material.Name}"

        # Try to get from style
        if hasattr(geometry, "materials"):
            materials = geometry.materials
            if materials:
                # Use first material as ID
                mat = materials[0]
                if hasattr(mat, "original_name") and mat.original_name():
                    return f"mat_{mat.original_name()}"

                # If no name, use color as unique identifier
                if hasattr(mat, "diffuse"):
                    color = mat.diffuse
                    r = color.r() if callable(getattr(color, "r", None)) else 0.8
                    g = color.g() if callable(getattr(color, "g", None)) else 0.8
                    b = color.b() if callable(getattr(color, "b", None)) else 0.8
                    # Create ID from color values (rounded to 2 decimals)
                    return f"mat_rgb_{int(r * 100)}_{int(g * 100)}_{int(b * 100)}"

        # Default: use IFC class
        return f"mat_{product.is_a()}"

    def _extract_material(self, product: Any, geometry: Any) -> Dict[str, Any]:
        """Extract material properties from product/geometry.

        Returns:
            Dict with 'color' (RGBA tuple 0-1 range) and optionally other properties
        """
        # Try to get material color from geometry
        if hasattr(geometry, "materials") and geometry.materials:
            mat = geometry.materials[0]
            if hasattr(mat, "diffuse"):
                # diffuse is a colour object with r(), g(), b() methods
                color = mat.diffuse
                r = color.r() if callable(getattr(color, "r", None)) else 0.8
                g = color.g() if callable(getattr(color, "g", None)) else 0.8
                b = color.b() if callable(getattr(color, "b", None)) else 0.8
                return {"color": (r, g, b, 1.0)}

        # Default gray color
        return {"color": (0.8, 0.8, 0.8, 1.0)}

    def _center_meshes(self, meshes: List[Dict[str, Any]]) -> None:
        """Center all meshes around origin.

        Modifies meshes in-place.
        """
        if not meshes:
            return

        # Calculate bounding box across all meshes
        all_vertices = np.vstack([mesh["vertices"] for mesh in meshes])
        min_bounds = all_vertices.min(axis=0)
        max_bounds = all_vertices.max(axis=0)
        center = (min_bounds + max_bounds) / 2

        # Translate all meshes
        for mesh in meshes:
            mesh["vertices"] -= center

    def _build_gltf(
        self, meshes: List[Dict[str, Any]], materials_map: Dict[str, Dict[str, Any]]
    ) -> pygltflib.GLTF2:
        """Build glTF structure from meshes and materials.

        Args:
            meshes: List of mesh dicts
            materials_map: Material properties by ID

        Returns:
            GLTF2 object ready to save
        """
        gltf = pygltflib.GLTF2()

        # Binary buffer to hold all geometry data
        buffer_data = bytearray()

        # Track buffer views and accessors
        buffer_views = []
        accessors = []
        primitives_list = []

        # Create materials
        material_id_to_index: Dict[str, int] = {}
        gltf_materials = []

        for mat_id, mat_props in materials_map.items():
            color = mat_props.get("color", (0.8, 0.8, 0.8, 1.0))
            gltf_materials.append(
                pygltflib.Material(
                    name=mat_id,
                    pbrMetallicRoughness=pygltflib.PbrMetallicRoughness(
                        baseColorFactor=list(color),
                        metallicFactor=0.0,
                        roughnessFactor=1.0,
                    ),
                )
            )
            material_id_to_index[mat_id] = len(gltf_materials) - 1

        gltf.materials = gltf_materials

        # Process each mesh
        for mesh in meshes:
            vertices = mesh["vertices"].astype(np.float32)
            indices = mesh["indices"].astype(np.uint32)
            material_id = mesh["material_id"]

            # Add vertices to buffer
            vertex_offset = len(buffer_data)
            buffer_data.extend(vertices.tobytes())

            # Create buffer view and accessor for vertices
            buffer_views.append(
                pygltflib.BufferView(
                    buffer=0,
                    byteOffset=vertex_offset,
                    byteLength=len(vertices.tobytes()),
                    target=pygltflib.ARRAY_BUFFER,
                )
            )
            vertex_buffer_view_idx = len(buffer_views) - 1

            # Calculate min/max for vertices (required by glTF)
            min_vals = vertices.min(axis=0).tolist()
            max_vals = vertices.max(axis=0).tolist()

            accessors.append(
                pygltflib.Accessor(
                    bufferView=vertex_buffer_view_idx,
                    componentType=pygltflib.FLOAT,
                    count=len(vertices),
                    type=pygltflib.VEC3,
                    min=min_vals,
                    max=max_vals,
                )
            )
            vertex_accessor_idx = len(accessors) - 1

            # Add indices to buffer (align to 4-byte boundary)
            padding = (4 - len(buffer_data) % 4) % 4
            buffer_data.extend(b"\x00" * padding)

            index_offset = len(buffer_data)
            buffer_data.extend(indices.tobytes())

            # Create buffer view and accessor for indices
            buffer_views.append(
                pygltflib.BufferView(
                    buffer=0,
                    byteOffset=index_offset,
                    byteLength=len(indices.tobytes()),
                    target=pygltflib.ELEMENT_ARRAY_BUFFER,
                )
            )
            index_buffer_view_idx = len(buffer_views) - 1

            accessors.append(
                pygltflib.Accessor(
                    bufferView=index_buffer_view_idx,
                    componentType=pygltflib.UNSIGNED_INT,
                    count=len(indices),
                    type=pygltflib.SCALAR,
                )
            )
            index_accessor_idx = len(accessors) - 1

            # Create primitive
            primitive = pygltflib.Primitive(
                attributes=pygltflib.Attributes(POSITION=vertex_accessor_idx),
                indices=index_accessor_idx,
                material=material_id_to_index.get(material_id, 0),
            )
            primitives_list.append((mesh["name"], [primitive]))

        # Create meshes (one per IFC product)
        gltf_meshes = []
        for name, primitives in primitives_list:
            gltf_meshes.append(pygltflib.Mesh(name=name, primitives=primitives))

        # Create nodes (one per mesh)
        nodes = []
        for i in range(len(gltf_meshes)):
            nodes.append(pygltflib.Node(mesh=i))

        # Create scene
        scene = pygltflib.Scene(nodes=list(range(len(nodes))))

        # Assemble glTF
        gltf.scenes = [scene]
        gltf.scene = 0
        gltf.meshes = gltf_meshes
        gltf.nodes = nodes
        gltf.bufferViews = buffer_views
        gltf.accessors = accessors

        # Add buffer
        gltf.buffers = [pygltflib.Buffer(byteLength=len(buffer_data))]
        gltf.set_binary_blob(bytes(buffer_data))

        return gltf


def convert_ifc_to_glb(
    ifc_path: Path,
    glb_path: Path,
    use_world_coords: bool = True,
    generate_uvs: bool = True,
    center_model: bool = False,
    compress: bool = True,
) -> None:
    """Convenience function to convert IFC to GLB.

    Args:
        ifc_path: Input IFC file
        glb_path: Output GLB file
        use_world_coords: Use world coordinates (preserves geo-location)
        generate_uvs: Generate UV coordinates for textures
        center_model: Center model at origin (useful for web viewers)
        compress: Gzip compress output (default: True, adds .gz extension)

    Example:
        >>> from giskit.exporters.glb_exporter import convert_ifc_to_glb
        >>> convert_ifc_to_glb('input.ifc', 'output.glb')
    """
    exporter = GLBExporter()
    exporter.ifc_to_glb(
        ifc_path,
        glb_path,
        use_world_coords=use_world_coords,
        generate_uvs=generate_uvs,
        center_model=center_model,
        compress=compress,
    )


def check_glb_export_availability() -> dict:
    """Check GLB export availability and return info.

    Returns:
        Dict with 'available' (bool) and dependency info
    """
    exporter = GLBExporter()

    info = {
        "available": exporter.is_available(),
        "method": "ifcopenshell.geom (Python API)",
    }

    # Check versions
    try:
        import ifcopenshell

        info["ifcopenshell_version"] = ifcopenshell.version
    except (ImportError, AttributeError):
        pass

    try:
        import pygltflib

        info["pygltflib_version"] = pygltflib.__version__
    except (ImportError, AttributeError):
        pass

    return info
