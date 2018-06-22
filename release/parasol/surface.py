"""
Raster data handlers
"""

import logging
import psycopg2 as pg
import numpy as np
import math
from scipy.spatial import cKDTree
import gdal
import osr
import subprocess
from pdb import set_trace
import tempfile
import matplotlib
from matplotlib import pyplot as plt
import argparse
import os 
from glob import glob
import tempfile

import parasol
from parasol import lidar
from parasol.common import tile_limits
from parasol import DATA_DIR, PRJ_SRID, DOMAIN_XLIM, DOMAIN_YLIM

logger = logging.getLogger(__name__)


# constants
RESOLUTION = 1 # meters
PAD = 10 # meters
TILE_DIM = 1000 # meters


def grid_points(x_min, x_max, y_min, y_max):
    """
    Grid scattered points using kNN median filter

    Arguments:
        x_min, x_max, y_min, y_max: floats, limits for bounding box 
        grnd: set True to compute surface from ground returns, False to compute
            surface from (first) non-ground returns
    
    Returns: x_vec, y_vec, z_grd
        x_vec, y_vec: numpy 1D arrays, x and y coordinate axes
        z_surf, z_grnd: numpy 2D arrays, elevation grids 
    """

    # build output grid spanning bbox
    x_vec = np.arange(math.floor(x_min), math.floor(x_max), RESOLUTION)   
    y_vec = np.arange(math.floor(y_min), math.floor(y_max), RESOLUTION)   
    x_grd, y_grd = np.meshgrid(x_vec, y_vec)

    # retrieve data, including a pad on all sides
    pts = lidar.retrieve(x_min-PAD, y_min-PAD, x_max+PAD, y_max+PAD)

    # extract ground points
    grnd_idx = []
    for idx, pt in enumerate(pts):
        if pt[3] == pt[4]  and pt[5] == 2:
            # last or only return, classified as "ground"
            grnd_idx.append(idx)
    grnd_pts = pts[grnd_idx, :3]
    
    # extract upper surface points
    surf_idx = []
    for idx, pt in enumerate(pts):
        if (pt[3] == 1 or pt[4] == 1) and pt[5] == 1:
            # first or only return, classified as "default"
            surf_idx.append(idx)
    surf_pts = pts[surf_idx, :3]
    del pts

    z_grds = []
    for pts in [grnd_pts, surf_pts]: 
        # extract [x, y] and z arrays
        xy = pts[:, :2]
        zz = pts[:,  2]

        # find NN for all grid points
        tree = cKDTree(xy) 
        xy_grd = np.hstack([x_grd.reshape((-1,1)), y_grd.reshape((-1,1))])
        nn_dist, nn_idx = tree.query(xy_grd, k=16)

        # compute local medians
        z_grds.append(np.median(zz[nn_idx], axis=1).reshape(x_grd.shape))

    return x_vec, y_vec, z_grds[0], z_grds[1]


def create_geotiff(filename, x_vec, y_vec, z_grd):
    """
    Write input array as GeoTiff raster
    
    Arguments:
        filename: string, path to write GeoTiff file
        x_vec, y_vec: numpy 1D arrays, x and y coordinate axes
        z_grd: numpy 2D array, elevation grid 

    Returns: Nothing, writes result to file
    """
    # invert y-axis
    y_vec = y_vec[::-1]
    z_grd = z_grd[::-1,:]
    # create file
    rows, cols = z_grd.shape
    driver = gdal.GetDriverByName('GTiff')
    outRaster = driver.Create(filename, cols, rows, 1, gdal.GDT_Float32)
    outRaster.SetGeoTransform((x_vec[0], RESOLUTION, 0, y_vec[0], 0, -RESOLUTION))
    outband = outRaster.GetRasterBand(1)
    outband.WriteArray(z_grd)
    outRasterSRS = osr.SpatialReference()
    outRasterSRS.ImportFromEPSG(PRJ_SRID)
    outRaster.SetProjection(outRasterSRS.ExportToWkt())
    outband.FlushCache()
    # clean up
    driver = outRaster = outband = None


def create_surfaces(x_min, x_max, y_min, y_max, x_tile, y_tile):
    """
    Generate rasters and upload to database, tile-by-tile

    Arguments:
        x_min, x_max, y_min, y_max: floats, limits for the full region-of-interest
        x_tile, y_tile: floats, desired dimensions for generated tiles, note that
            the actual dimensions are adjusted to evenly divide the ROI
    
    Returns: nothing
    """
    tiles = tile_limits(x_min, x_max, y_min, y_max, x_tile, y_tile)
    num_tiles = len(tiles)

    modes = ['add'] * len(tiles)
    modes[0] = 'create'
    modes[-1] = 'finish'

    # generate tiles
    for ii, tile in enumerate(tiles):
        logger.info(f'Generating tile {ii+1} of {num_tiles}')
        x_vec, y_vec, z_grnd, z_surf = grid_points(**tile)
        
        grnd_name = os.path.join(DATA_DIR, 'ground_tile_{:04d}.tif'.format(ii))
        create_geotiff(grnd_name, x_vec, y_vec, z_grnd)
        logger.info(f'Wrote tile {grnd_name}')
        
        surf_name = os.path.join(DATA_DIR, 'surface_tile_{:04d}.tif'.format(ii))
        create_geotiff(surf_name, x_vec, y_vec, z_surf)
        logger.info(f'Wrote tile {surf_name}')

    # merge tiles
    logger.info('Merging tiles')
    for prefix in ['ground', 'surface']:
        cmd =  ['gdal_merge.py']
        cmd.extend(glob(os.path.join(DATA_DIR, prefix + '_tile_*.tif')))
        cmd.extend(['-of', 'GTiff', '-o', os.path.join(DATA_DIR, prefix + '.tif')])
        subprocess.run(cmd)


# INCOMPLETE
def retrieve(x_min, x_max, y_min, y_max, which):
    """
    Retrieve subset within specified ROI
    
    Arguments:
        minx, maxx, miny, maxy: floats, limits for bounding box 
        which: string, which raster to retrieve data from, must be one of
            'surface', 'ground'

    Returns: numpy array
    """
    # get raster file name
    if which == 'surface':
        src_file = os.path.join(DATA_DIR, 'surface.tif')
    elif which == 'ground':
        src_file = os.path.join(DATA_DIR, 'ground.tif')
    else:
        raise ValueError('Invalid choice for "which" variable')

    # get subset as file
    with tempfile.NamedTemporaryFile() as fp:
        dest_file = fp.name()
        subprocess.run(['gdal_translate', '-of', 'GTiff', '-projwin',
            str(x_min), str(y_max), str(x_max), str(y_min), src_file, dest_file])

    # TODO: read file 


# command line utilities -----------------------------------------------------


def initialize_cli():
    """Command line utility for initializing the surface/ground databases"""
    ap = argparse.ArgumentParser(
        description="Initialize Parasol surface & ground raster databases - clobbers existing!",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter) 
    ap.add_argument('--log', type=str, default='info', help="select logging level",
                    choices=['debug', 'info', 'warning', 'error', 'critical'])
    ap.add_argument('--dryrun', action='store_true', help='Set to preview only')
    args = ap.parse_args()

    log_lvl = getattr(logging, args.log.upper())
    logging.basicConfig(level=log_lvl)
    logger.setLevel(log_lvl)

    if (args.dryrun):
        tiles = tile_limits(DOMAIN_XLIM[0], DOMAIN_XLIM[1], DOMAIN_YLIM[0],
            DOMAIN_YLIM[1], TILE_DIM, TILE_DIM)
        print(f'Compute raster in domain: [[{DOMAIN_XLIM}], [{DOMAIN_YLIM}]]')
        print(f'Num tiles: {len(tiles)}')
    
    else:
        create_surfaces(DOMAIN_XLIM[0], DOMAIN_XLIM[1], DOMAIN_YLIM[0],
            DOMAIN_YLIM[1], TILE_DIM, TILE_DIM)