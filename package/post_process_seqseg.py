import pyvista as pv 
import vtk
import numpy as np
from scipy.spatial.distance import pdist, squareform
import pdb
import os
from __init__ import *
from scipy.spatial.distance import cdist
import numpy as np
from scipy.sparse.csgraph import minimum_spanning_tree
import math 
        
def clip_segseq_TF():
    '''
    this function asks the user if they want to clip the seqseg model
    and if so, it runs the post_process_seqseg.py script to clip the seqseg model
    '''
    while True:
        print( "\n Do you want to automatically clip the seqseg model? \n")
        print('note: depending on your model complexity (are there any branch outlet next to other vessels),this method may not be robust.')
        print('Recommend using SimVascular to clip the caps open tailoring to your needs.')
        answer = input(
            "Do you want to automatically clip the seqseg model? (yes/no): "
        )
        if answer.lower() == "yes":
            print("Clipping the seqseg model...")
            return True
        elif answer.lower() == "no":
            print("Skipping clipping of the seqseg model.")
            return False
        else:
            print("Invalid input. Please enter 'yes' or 'no'.")



def compute_mst_per_branch(cl_dict):
    """
    Input:
      cl_dict: {branch_id: [(x,y,z), …], …}
    Returns:
      mst_edges: {branch_id: [(i,j), …], …}
        where each (i,j) is an edge in the MST over that branch’s points
        using the point‐indices in the original list.
    """
    mst_edges = {}
    for cid, pts in cl_dict.items():
        pts_arr = np.array(pts)              # shape (N,3)
        if pts_arr.shape[0] < 2:
            mst_edges[cid] = []
            continue

        # 1) Compute full N×N distance matrix
        D = squareform(pdist(pts_arr))
        # 2) Minimum spanning tree (returns sparse)
        mst_sparse = minimum_spanning_tree(D)
        # 3) Extract edges: use the COO format for simplicity
        coo = mst_sparse.tocoo()
        edges = list(zip(coo.row.tolist(), coo.col.tolist()))
        mst_edges[cid] = edges

    return mst_edges

def get_ordered_centerlines(cl_dict, mst_trees):
    """
    Reorders each branch’s points according to its MST edges.

    Parameters
    ----------
    cl_dict : dict[int, list[tuple]]
        Mapping branch_id → list of (x,y,z) points (unsorted).
    mst_trees : dict[int, list[tuple[int,int]]]
        Mapping branch_id → list of edges (i,j) from compute_mst_per_branch.

    Returns
    -------
    ordered_dict : dict[int, list[tuple]]
        Mapping branch_id → list of (x,y,z) points ordered along the MST.
    """
    ordered_dict = {}

    for cid, edges in mst_trees.items():
        pts = cl_dict[cid]
        N = len(pts)
        # trivial cases
        if N <= 1:
            ordered_dict[cid] = pts.copy()
            continue

        # 1) build adjacency list
        adj = {i: [] for i in range(N)}
        for i, j in edges:
            adj[i].append(j)
            adj[j].append(i)

        # 2) find endpoints (nodes of degree 1)
        endpoints = [i for i, nbrs in adj.items() if len(nbrs) == 1]
        start = endpoints[0] if endpoints else 0

        # 3) traverse the tree (DFS) to collect indices in order
        visited = set()
        ordered_idx = []

        def dfs(u):
            visited.add(u)
            ordered_idx.append(u)
            for v in adj[u]:
                if v not in visited:
                    dfs(v)

        dfs(start)

        # 4) map indices back to coordinates
        ordered_dict[cid] = [pts[k] for k in ordered_idx]

    return ordered_dict

def orient_centerlines(ordered_cl_dict, reference_point=None):
    """
    Ensure every centerline branch starts closest to `reference_point`.

    Parameters
    ----------
    ordered_cl_dict : dict[int, list[tuple]]
        branch_id → its list of (x,y,z) in some end‑to‑end order
    reference_point : array‑like of shape (3,), optional
       The “root” location all branch‐starts should approximate.
       If None, we auto‑compute it as the centroid of all branch‐endpoints.

    Returns
    -------
    oriented_cl_dict : dict[int, list[tuple]]
        Same keys, but each value reversed if needed so that its first
        point is the endpoint closest to reference_point.
    """
    # 1) compute a reference if none given
    if reference_point is None:
        # collect all candidates: every branch's two ends
        pts = []
        for pts_list in ordered_cl_dict.values():
            #pdb.set_trace()
            pts.append(pts_list[0])
            pts.append(pts_list[-1])
        reference_point = np.mean(np.array(pts), axis=0)

    ref = np.array(reference_point)

    # 2) re‑orient each branch
    oriented = {}
    for cid, pts_list in ordered_cl_dict.items():
        arr = np.array(pts_list)
        d0 = np.linalg.norm(arr[0]  - ref)
        d1 = np.linalg.norm(arr[-1] - ref)
        if d1 < d0:
            # end is closer → flip
            oriented[cid] = pts_list[::-1]
        else:
            oriented[cid] = pts_list.copy()

    return oriented

def get_clipping_box_parameters(final_cl,clpd):
    """
    get endpoints (the last 90 percent), unit vector, and cross sectional area of each line
    """
    clipping_params = {}
    for cid, coords in final_cl.items():
        start = np.array(coords[0])
        length = len(coords)
        length_to_use = int(length * 0.95)  # use the last 90 percent
        second_to_last = np.array(coords[length_to_use - 1])
        end = np.array(coords[length_to_use])
        unit_vector = (end - second_to_last) / np.linalg.norm(end - second_to_last)
        
        # get cross sectional area by reading the centerline polydata and extract attribute MaximumInscribedSphereRadius
        # this is a proxy for the cross sectional area
        
        index = np.where(clpd.points == end)[0][0]
        cross_sectional_area = clpd['MaximumInscribedSphereRadius'][index] ** 2 * np.pi   


        clipping_params[cid] = {
            'start': start,
            'end': end,
            'unit_vector': unit_vector,
            'cross_sectional_area': cross_sectional_area
        }
    return clipping_params
def generate_oriented_boxes(clipping_params, output_folder, box_scale=3):
    """
    Args:
      clipping_params: dict mapping an integer key to a dict with:
        - 'start':      np.array([x,y,z], dtype=float)
        - 'unit_vector':np.array([ux,uy,uz], dtype=float)
        - 'cross_sectional_area': float
      output_folder:   str, path to write box_<key>.vtp files
      box_scale:       float, multiplier for box size

    Returns:
      (combined_polydata, list_of_individual_polydata)
    """
    if not os.path.isdir(output_folder):
        os.makedirs(output_folder, exist_ok=True)

    append_all = vtk.vtkAppendPolyData()
    pd_list = []

    for idx, params in clipping_params.items():
        end = params['end']
        uv    = params['unit_vector']
        area  = float(params['cross_sectional_area'])
        # compute equivalent radius from area = π r^2
        radius = math.sqrt(area / math.pi)

        # compute the box center offset along the unit vector
        center = [
            end[0] + 0.5 * box_scale * radius * uv[0],
            end[1] + 0.5 * box_scale * radius * uv[1],
            end[2] + 0.5 * box_scale * radius * uv[2],
        ]

        # build the cube
        cube = vtk.vtkCubeSource()
        cube.SetXLength(box_scale * radius)
        cube.SetYLength(box_scale * radius)
        cube.SetZLength(box_scale * radius)
        cube.Update()

        # figure out rotation to align cube's z-axis with uv
        z_axis = np.array([0.0, 0.0, 1.0])
        rot_axis = np.cross(z_axis, uv)
        angle_deg = np.degrees(np.arccos(np.dot(uv, z_axis)))

        tf = vtk.vtkTransform()
        tf.Translate(center)
        if np.linalg.norm(rot_axis) > 1e-8:
            tf.RotateWXYZ(angle_deg, rot_axis)

        tf_filter = vtk.vtkTransformPolyDataFilter()
        tf_filter.SetInputConnection(cube.GetOutputPort())
        tf_filter.SetTransform(tf)
        tf_filter.Update()

        pd = tf_filter.GetOutput()
        pd_list.append(pd)
        append_all.AddInputData(pd)

        

    append_all.Update()
   
    writer = vtk.vtkXMLPolyDataWriter()
    out_file = os.path.join(output_folder, f"box_for_clipping.vtp")
    writer.SetFileName(out_file)
    writer.SetInputData(append_all.GetOutput())
    writer.Write()
    return append_all.GetOutput(), pd_list

def write_polydata(file_path, polydata):
    """
    Write a vtkPolyData object to a file.
    
    Args:
        file_path (str): The path to the output file.
        polydata (vtk.vtkPolyData): The polydata to write.
    """
    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(file_path)
    writer.SetInputData(polydata)
    writer.Write()
    print(f"PolyData written to {file_path}")

def bryan_clip_surface(surf1, surf2):
    # Create an implicit function from surf2
    implicit_function = vtk.vtkImplicitPolyDataDistance()
    implicit_function.SetInput(surf2)

    # Create a vtkClipPolyData filter and set the input and implicit function
    clipper = vtk.vtkClipPolyData()
    clipper.SetInputData(surf1)
    clipper.SetClipFunction(implicit_function)
    clipper.InsideOutOff()  # keep the part of surf1 outside of surf2
    clipper.Update()

    # Get the output polyData with the part enclosed by surf2 clipped away
    clipped_surf1 = clipper.GetOutput()

    return clipped_surf1

if __name__ == "__main__":

    from collections import defaultdict
    import sys
    ans = clip_segseq_TF()
    if not ans or not os.path.exists(seqseg_cl):
        print('You chose not to clip the seqseg model, or the rough seqseg centerline file does not exist.')
        print("please manually clip your surface, and save it according to your <clipped_seqseg_results> from init file  .")
        sys.exit(0)
    # 1) Read your centerline VTP
    clpd = pv.read(seqseg_cl)
    surf_pd = pv.read(segseqed_model)
    clpts = clpd.points            # (N,3) array
    cl_ids = clpd['CenterlineId']  # (N,) array of ints

    # 2) Build dict: key = branch ID, value = list of (x,y,z)
    cl_dict = defaultdict(list)
    for pt, cid in zip(clpts, cl_ids):
        cl_dict[int(cid)].append(tuple(pt))

    mst_trees = compute_mst_per_branch(cl_dict)

    # assume cl_dict and mst_trees already exist
    ordered_centerlines = get_ordered_centerlines(cl_dict, mst_trees)

    for cid, coords in ordered_centerlines.items():
        print(f"Branch {cid}: {len(coords)} ordered points")
        # coords is now the connected, end‑to‑end sequence of your (x,y,z) tuples
    final_cl = orient_centerlines(ordered_centerlines)

    clipping_params = get_clipping_box_parameters(final_cl, clpd)
    #pdb.set_trace()
    # generate oriented boxes
    boxpd, boxpdlst = generate_oriented_boxes(
        clipping_params,
        output_folder=master_folder,
        box_scale=10.0  # adjust as needed
    )
    
    # 3) Clip the surface using the boxes
    # Assuming you have a surface to clip, e.g., from segseqed_model
    clipped = bryan_clip_surface(surf_pd, boxpd)
    # 4) Save the clipped surface
    clipped_file = os.path.join(master_folder, 'postprocessed_seqseg.vtp')
    write_polydata(clipped_file, clipped)
    clipped = pv.read(clipped_file)  # to visualize in PyVista
    keep_largest = clipped.extract_largest() 
    write_polydata(os.path.join(master_folder, 'postprocessed_seqseg.vtp'), keep_largest)
    
    


    # # print each endpoint 
    # for cid, coords in final_cl.items():
    #     print(f"Branch {cid}: {coords[0]} to {coords[-1]}")

    # now use final_cl to get each line's endpts, unit vector, and cross sectional area to clip surfaces


    pdb.set_trace()