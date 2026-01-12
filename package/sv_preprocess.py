from sv import *
from sv_rom_simulation import *
from sv_auto_lv_modeling.modeling.src import meshing as svmeshtool
# from inflow_editor import * # we are running this in a subprocess
import numpy as np
import pdb
import vtk
from vtk.util import numpy_support
from vtk.util.numpy_support import vtk_to_numpy as v2n
from vtk.util.numpy_support import numpy_to_vtk as n2v
import os 
import shutil
import time
import sys
import csv

import warnings
import subprocess

# ========================================================================
# ============================ intialize  ================================

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))
from package import *
from package.helper_func import *
# ========================================================================
# ============================ preprocess  ================================
# Modified by Claude: Improved user prompts for better readability

'''
to use this code
/usr/local/sv/simvascular/2023-03-27/simvascular --python -- /home/bg2881/Documents/MIROS/MIROS/package/main1D.py
'''

# --- Helper function for formatted output (added by Claude) ---
def print_section_header(title):
    """Print a formatted section header for better readability."""
    print("\n" + "=" * 70)
    print("  [STEP] " + title)
    print("=" * 70)

def print_status(message):
    """Print a status message with visual indicator."""
    print("  ✓ " + message)

def print_info(message):
    """Print an info message."""
    print("  → " + message)
# --- End helper functions ---

### here! model(clipped_seqseg_results) needs to have boundary clipped open

print_section_header("PRE-PROCESSING: Model Setup")

# create master folder if not exists
if not os.path.exists(master_folder):
    os.makedirs(master_folder)
print_status("Results folder: " + master_folder)


# read the model using sv built-in function
segseqed_vtp = read_surface(clipped_seqseg_results,'vtp',None)

# load the model into a sv modeler object
modeler = modeling.PolyData(segseqed_vtp)

# compute faces (only 1 being the wall)
modeler.compute_boundary_faces(90.0)

# fill holes with ids
filled = vmtk.cap(segseqed_vtp)
modeler = modeling.PolyData(filled)

# ========================================================================
# Compute edge size (auto or user-specified)
# ========================================================================
if edge_size == 'auto':
    print_info("Computing adaptive edge size based on model geometry...")
    computed_edge_size = compute_adaptive_edge_size(modeler.get_polydata())
    edge_min_use = computed_edge_size
    edge_max_use = computed_edge_size
    print_status("Adaptive edge size: " + str(round(computed_edge_size, 4)))
else:
    edge_min_use = edge_min
    edge_max_use = edge_max
    print_info("Using user-specified edge size: " + str(edge_size))

# remesh the model, ensure boundary mesh quality
model_vtp = svmeshtool.remesh_polydata(modeler.get_polydata(), edge_min_use, edge_max_use)
modeler = modeling.PolyData(model_vtp)
write_polydata(os.path.join(master_folder, 'remeshed_model.vtp'), modeler.get_polydata())
print_status("Remeshed model saved: " + os.path.join(master_folder, 'remeshed_model.vtp'))

# ========================================================================
# === Generate Volume Mesh (Added by Claude for 3D result visualization) ===
# ========================================================================
print_info("Generating volume mesh for 3D visualization...")
print_info("This may take a few minutes...")

try:
    # Create mesh-complete directory
    mesh_complete_dir = os.path.join(master_folder, 'mesh-complete')
    if not os.path.exists(mesh_complete_dir):
        os.makedirs(mesh_complete_dir)

    # Use original clipped model (before remeshing) - this produces cleaner surfaces
    # The remeshed model can have non-manifold edges that prevent volume meshing
    surface_for_vol = read_surface(clipped_seqseg_results, 'vtp', None)
    modeler_for_vol = modeling.PolyData(surface_for_vol)

    # Cap the surface using vmtk (properly fills holes at outlets)
    print_info("Capping surface for volume mesh...")
    capped_surface = vmtk.cap(modeler_for_vol.get_polydata())

    # Load capped surface and compute boundary faces
    modeler_for_vol = modeling.PolyData(capped_surface)
    modeler_for_vol.compute_boundary_faces(angle=60.0)

    # Save processed model with face IDs
    processed_model_path = os.path.join(mesh_complete_dir, 'processed_surface.vtp')
    write_polydata(processed_model_path, modeler_for_vol.get_polydata())

    # Use TetGen to generate volume mesh
    tetgen_mesher = meshing.TetGen()
    tetgen_mesher.load_model(processed_model_path)

    # Get face IDs and set walls (face ID 1 is typically the wall)
    face_ids = tetgen_mesher.get_model_face_ids()
    print_info("Model face IDs: " + str(len(face_ids)) + " faces detected")

    # Set wall face IDs
    if 1 in face_ids:
        tetgen_mesher.set_walls([1])

    # Set meshing options - use coarser edge for faster volume mesh generation
    # Get model size for edge calculation
    bounds = capped_surface.GetBounds()
    max_dim = max(bounds[1]-bounds[0], bounds[3]-bounds[2], bounds[5]-bounds[4])
    vol_edge_size = max_dim * 0.03  # 3% of model size

    mesh_options = meshing.TetGenOptions(
        global_edge_size=vol_edge_size,
        surface_mesh_flag=False,  # Don't remesh surface, just create volume
        volume_mesh_flag=True
    )
    mesh_options.optimization = 3
    mesh_options.quality_ratio = 1.5

    # Generate the mesh
    tetgen_mesher.generate_mesh(mesh_options)

    # Get the volume and surface meshes
    volume_mesh = tetgen_mesher.get_mesh()
    surface_mesh = tetgen_mesher.get_surface()

    # Add GlobalNodeID array to volume mesh (required for result projection)
    num_points = volume_mesh.GetNumberOfPoints()
    global_node_ids = vtk.vtkIntArray()
    global_node_ids.SetName("GlobalNodeID")
    global_node_ids.SetNumberOfTuples(num_points)
    for i in range(num_points):
        global_node_ids.SetValue(i, i)
    volume_mesh.GetPointData().AddArray(global_node_ids)
    print_info("Added GlobalNodeID array for result projection")

    # Add GlobalNodeID to surface mesh as well
    num_surf_points = surface_mesh.GetNumberOfPoints()
    surf_node_ids = vtk.vtkIntArray()
    surf_node_ids.SetName("GlobalNodeID")
    surf_node_ids.SetNumberOfTuples(num_surf_points)
    for i in range(num_surf_points):
        surf_node_ids.SetValue(i, i)
    surface_mesh.GetPointData().AddArray(surf_node_ids)

    # Write volume mesh
    volume_mesh_path = os.path.join(mesh_complete_dir, 'mesh-complete.mesh.vtu')
    writer = vtk.vtkXMLUnstructuredGridWriter()
    writer.SetFileName(volume_mesh_path)
    writer.SetInputData(volume_mesh)
    writer.Write()
    print_status("Volume mesh saved: " + volume_mesh_path)
    print_info("  Points: " + str(volume_mesh.GetNumberOfPoints()) + ", Cells: " + str(volume_mesh.GetNumberOfCells()))

    # Write exterior surface
    exterior_path = os.path.join(mesh_complete_dir, 'mesh-complete.exterior.vtp')
    write_polydata(exterior_path, surface_mesh)
    print_status("Exterior surface saved: " + exterior_path)

    print_status("Volume mesh generation complete!")

except Exception as e:
    print("  [WARNING] Volume mesh generation failed: " + str(e))
    print("  [INFO] 3D visualization will not be available, but 1D/0D simulations can still run.")
    print("  [INFO] You can generate the volume mesh manually in SimVascular if needed.")

# ========================================================================

# create a folder and write out caps
caps_folder = os.path.join(master_folder, 'caps_and_wall')
if not os.path.exists(caps_folder):
    os.makedirs(caps_folder)
write_caps_and_wall(caps_folder, modeler)
print_status("Caps and wall written to: " + caps_folder)

# --- User input section (Modified by Claude) ---
print("\n" + "-" * 70)
print("  >>> USER INPUT REQUIRED <<<")
print("-" * 70)
print("  Please define the inflow cap from the caps in: " + caps_folder)
print("-" * 70)
get_inlet_cap_name(caps_folder)

# create rcr boundary condition template from caps
create_rcr_bc_template(caps_folder, os.path.join(master_folder, bc_filename))
print_status("RCR boundary condition template created: " + os.path.join(master_folder, bc_filename))

# compute cap areas use vtk
helper_txt_path = write_helper_txt(master_folder, caps_folder)

# --- User action required notice (Modified by Claude) ---
print("\n" + "-" * 70)
print("  >>> ACTION REQUIRED <<<")
print("-" * 70)
print("  1. Edit the RCR boundary condition file:")
print("     " + os.path.join(master_folder, bc_filename))
print("  2. Reference model_info.txt for cap areas to help set RCR values")
print("-" * 70)
print("  Pre-processing complete. Continuing to next step...")
print("-" * 70 + "\n")

