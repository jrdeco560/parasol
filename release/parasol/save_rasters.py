"""
Retrieve rad rasters from the Grass database -- this should not be so hard
"""

import os
import subprocess

os.environ['GISBASE'] = '/usr/lib/grass74'
os.environ['GISRC'] = '/home/keith/.grass7/rc'

for tt in range(0, 2401, 25):
    num_str = '{:04d}'.format(tt)
    time_str = num_str[0:2] + '.' + num_str[2:]
    layer_name = f'top_rad_{time_str}@mvp'
    file_name = f'/home/keith/.parasol/lidar/rad/rad_{time_str}.tif'
    subprocess.run(['grass74', '/home/keith/.grassdata/parasol-dev/mvp', '--exec', 'r.out.gdal', f'input={layer_name}', f'output={file_name}', 'format=GTiff'])

