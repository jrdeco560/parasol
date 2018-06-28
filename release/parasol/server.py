"""
Flask server for Parasol API/UI
"""

import flask
import argparse
import os
from pkg_resources import resource_filename
import psycopg2
from pdb import set_trace

from parasol import cfg, routing


# create app
app = flask.Flask('parasol')


# endpoints ------------------------------------------------------------------


@app.route('/', methods=["GET"])
@app.route('/ui', methods=["GET"])
def main():
    """Main Parasol user interface"""
    return flask.render_template('index.html')


@app.route('/route', methods=['GET'])
def route():
    """
    Compute route between specified start and end points

    Parameters (URL query string):
        lat0, lon0: floats, start point latitude, longitude
        lat1, lon1: floats, end point latitude, longitude
        beta: float, sun/shade preference parameter 

    Returns: optimal route as geoJSON
    """
    lat0 = float(flask.request.args.get('lat0'))
    lon0 = float(flask.request.args.get('lon0'))
    lat1 = float(flask.request.args.get('lat1'))
    lon1 = float(flask.request.args.get('lon1'))
    beta = float(flask.request.args.get('beta'))
    
    geojson = routing.route(lon0, lat0, lon1, lat1, beta)
    print(geojson)
    
    return flask.Response(status=200, response=geojson, mimetype='application/json')


# DEBUG
@app.route('/debug', methods=["GET"])
def bootstrap():
    return flask.render_template('new.html')


# command line ---------------------------------------------------------------


def cli():
    """Run Parasol on localhost with Flask built-in server"""
    ap = argparse.ArgumentParser(
        description='Parasol Navigation - MVP Edition',
        formatter_class= argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument('--debug', action='store_true',
        help='run server in "debug mode"')
    ap.add_argument('--host', type=str, default='0.0.0.0',
        help='hostname for flask server')
    ap.add_argument('--port', type=int, default=5000,
        help='server port number')
    args = ap.parse_args()

    app.run(host=args.host, port=args.port, debug=args.debug)
