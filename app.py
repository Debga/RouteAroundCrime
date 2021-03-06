#!/usr/bin/env python

from flask import Flask, url_for, request, render_template, jsonify
from flaskext.mysql import MySQL
from pprint import pprint
import json

import ConfigFile

app = Flask(__name__)
app.config.update(
    MYSQL_DATABASE_HOST = 'localhost',
    MYSQL_DATABASE_PORT = 3306,
    MYSQL_DATABASE_USER = ConfigFile.mysqlUser,
    MYSQL_DATABASE_PASSWORD = ConfigFile.mysqlPw,
    MYSQL_DATABASE_DB = 'crime'
    )

@app.route('/')
def index():
    """Render index page."""
    return render_template('index.html')

@app.route('/slides')
def slides():
    """Render slides page."""
    return render_template('slides.html')

@app.route('/_points_for_a_path', methods=['POST'])
def points_for_a_paths():
    """
    Called when user searches for routes. Returns JSON to client.

    Loops over steps of a Google route, gets start and end, passes those to FindCrimesNearALine.
    Assumes each step a straight line. (TO DO: check and account for curvy ones.)
    """
    route = json.loads(request.data)
    crimeDictsForRoutes = {'paths': []}
    if not len(route['legs']) == 1:
        raise ValueError, 'Unexpected number of "legs".'
    print 'In points_for_a_path: Number of steps', len(route['legs'][0]['steps'])

    steps = route['legs'][0]['steps']
    crimesForLinesList = []
    for step in steps:
        try:
            lat1 = step['start_location']['hb']
            lon1 = step['start_location']['ib']
            lat2 = step['end_location']['hb']
            lon2 = step['end_location']['ib']
        except KeyError:
            print 'WARNING: hacking the lat lon!'
            # TO DO: use .lat() and .lng() methods in JS, pass directly to here. More robust.
            latAndLonStrings = step['start_location'].keys()
            latAndLonStrings.sort()
            latString = latAndLonStrings[0]
            lonString = latAndLonStrings[1]
            if not (30.0 < step['start_location'][latString] < 50.0):
                print 'Swapping lat and lon strings'
                latString = latAndLonStrings[1]
                lonString = latAndLonStrings[0]
            lat1 = step['start_location'][latString]
            lon1 = step['start_location'][lonString]
            lat2 = step['end_location'][latString]
            lon2 = step['end_location'][lonString]


        crimesForLinesList.append(FindCrimesNearALine(lat1, lon1, lat2, lon2,
                                                      selectedPartOfDay=int(route['selectedPartOfDay'])))
            
    fullPathDict = {'pathCount': 0, 'latLons': [], 'stepByStepCount': [],
                    'partsOfDay': [], 'crimeWeights': []}
    for crimesJson in crimesForLinesList:
        cDict = json.loads(crimesJson.data)
        fullPathDict['pathCount'] += cDict['pathCount']
        fullPathDict['latLons'] += cDict['latLons']
        fullPathDict['stepByStepCount'].append(cDict['pathCount'])
        fullPathDict['partsOfDay'].append(cDict['partsOfDay'])
        fullPathDict['crimeWeights'].append(cDict['crimeWeights'])
    crimeDictsForRoutes['paths'].append(fullPathDict)
    crimeDictsForRoutes['routeNum'] = int(route['routeNum'])
    return jsonify(crimeDictsForRoutes)

def FindCrimesNearALine(latA, lonA, latB, lonB, d=60, nMax=10000, selectedPartOfDay=0):
    """
    Queries MySQL to get information about crimes near a line.
    
    Takes the lat and lon (in normal degrees) of two points A and B, a distance d in meters, max limit for query,
    and time of day.
    Querys the MySQL crime database.
    Returns a JSON object.
    Query doesn't compute distance between each point and the line. Rather, check if each point is in a box around
    the line by doting the point vector with the unit vectors parallel and perp to the line and doing inequalities.
    """

    # TO DO: Make more efficient by moving redundant operations outside loop, doing MySQL voodoo, moveing to DataFrame, or so.
    c = mysql.get_db().cursor()
    initializeMysqlCommand = """
    SET @latA = """+str(latA)+""";
    SET @lonA = """+str(lonA)+""";
    SET @latB = """+str(latB)+""";
    SET @lonB = """+str(lonB)+""";
    
    # use a first order approximation of the metric of a sphere,
    # centered on Oakland 12th St. city center
    SET @r = 6371009.0; # radius of the Earth in meters
    SET @c = 0.0174533; # conversion from degrees to radians
    SET @pathlength = Sqrt( Pow(@r*@c*(@latB-@latA), 2) + Cos(@latA*@c)*Cos(@latB*@c)*Pow(@r*@c*(@lonB-@lonA), 2));
    # v1 is unit vector parallel to BA line
    SET @v1y = @r*@c*(@latB-@latA) / @pathlength;
    SET @v1x = Cos(@latA*@c)*@r*@c*(@lonB-@lonA) / @pathlength;
    # v2 is perpendicular unit vector
    SET @v2x = -1 * @v1y;
    SET @v2y = @v1x;
    SET @localCos = Cos(@latA*@c);
    SET @d = """+str(d)+""";
    """
    #print 'initializeMysqlCommand:', initializeMysqlCommand
    c.execute(initializeMysqlCommand)
    c.close()
    c = mysql.get_db().cursor()

    #c.execute("SELECT @v1x, @v1y, @v2x, @v2y;")
    #pprint(c.fetchall())

    if selectedPartOfDay == 0:
        partOfDayConditionString = ''
    elif selectedPartOfDay in [1,2,4]:
        partOfDayConditionString = ' AND part_of_day = %i ' % selectedPartOfDay
    else:
        raise ValueError, selectedPartOfDay

    c.execute("""
    SELECT latitude, longitude, part_of_day, crime_weight
    FROM crime_index
    WHERE Abs((@r*@c*@localCos*longitude*@v2x + @r*@c*latitude*@v2y) -
           	  (@r*@c*@localCos*@lonA*@v2x + @r*@c*@latA*@v2y)) < @d # (input dot v2) minus (point on path dot v2)
    	  AND
    	  (@r*@c*@localCos*longitude*@v1x + @r*@c*latitude*@v1y) -
           	  (@r*@c*@localCos*@lonA*@v1x + @r*@c*@latA*@v1y) > -@d/2 # (input dot v1) minus (point1 on path dot v1)
    	  AND
    	  (@r*@c*@localCos*longitude*@v1x + @r*@c*latitude*@v1y) -
           	  (@r*@c*@localCos*@lonB*@v1x + @r*@c*@latB*@v1y) < @d/2 # (input dot v1) minus (point2 on path dot v1)
"""+partOfDayConditionString+"""
    LIMIT """+str(nMax)+""";
    """)
    sqlTuple = c.fetchall()
    #pprint(sqlTuple)
    
    latLonList = []
    partOfDayList = []
    crimeWeightList = []
    for ll in sqlTuple:
        latLonList.append([float(ll[0]), float(ll[1])])
        partOfDayList.append(int(ll[2]))
        crimeWeightList.append(float(ll[3]))

    if len(sqlTuple) <= nMax:
        countResult = len(sqlTuple)
    else:
        c.execute("""
        SELECT COUNT(*)
        FROM crime_index
        WHERE Abs((@r*@c*@localCos*longitude*@v2x + @r*@c*latitude*@v2y) -
               	  (@r*@c*@localCos*@lonA*@v2x + @r*@c*@latA*@v2y)) < @d # (input dot v2) minus (point on path dot v2)
        	  AND
        	  (@r*@c*@localCos*longitude*@v1x + @r*@c*latitude*@v1y) -
               	  (@r*@c*@localCos*@lonA*@v1x + @r*@c*@latA*@v1y) > -@d/2 # (input dot v1) minus (point1 on path dot v1)
        	  AND
        	  (@r*@c*@localCos*longitude*@v1x + @r*@c*latitude*@v1y) -
               	  (@r*@c*@localCos*@lonB*@v1x + @r*@c*@latB*@v1y) < @d/2 # (input dot v1) minus (point2 on path dot v1)
"""+partOfDayConditionString+"""
        ;
        """)
        
        countResult = c.fetchall()

    return jsonify(latLons=latLonList,
                   pathCount=countResult,
                   partsOfDay=partOfDayList,
                   crimeWeights=crimeWeightList)


if __name__ == '__main__':
    app.debug = ConfigFile.debug

    mysql = MySQL()
    mysql.init_app(app)

    app.run(host=ConfigFile.host, port=ConfigFile.port)
