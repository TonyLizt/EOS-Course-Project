"""Independent REAL Orekit point oracle for versioned physics test migration.

No imports from visibility/attitude_frames: construct the orbit and frames from
raw fields, multiply matrices explicitly, and test camera half-spaces directly.
This is numerical cross-validation, NEVER a continuous interval certificate.
"""
from datetime import timedelta
import math
import hashlib
import json
import inspect
from pathlib import Path
from utils.time_parsing import parse_orbit_epoch


def frozen():
    raw=(Path(__file__).parent/'fixtures/nadir_relative_v2.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='edbb4787169b47834a3b4ad70de140210c8e4e120fdc61fed43b27f2c1369b51'
    data=json.loads(raw)
    assert data['reference_sha256']==hashlib.sha256(inspect.getsource(reference).encode()).hexdigest()
    return data


def assert_point_close(test, actual, expected):
    """Numerical regression tolerance only; never used to accept a certificate."""
    test.assertEqual(actual.keys(),expected.keys())
    for key,want in expected.items():
        if type(want) is float:
            test.assertAlmostEqual(actual[key],want,delta=1e-8)
        elif key=='relative_matrix':
            for one,two in zip(actual[key],want):
                for a,b in zip(one,two):test.assertAlmostEqual(a,b,delta=1e-12)
        elif isinstance(want,list):
            test.assertEqual(len(actual[key]),len(want))
            for a,b in zip(actual[key],want):test.assertAlmostEqual(a,b,delta=1e-8)
        else:test.assertEqual(actual[key],want)


def reference(satellite, location, *, minimum=5., legacy_absolute=False):
    from org.orekit.frames import FramesFactory
    from org.orekit.utils import Constants, IERSConventions
    from org.orekit.bodies import OneAxisEllipsoid, GeodeticPoint
    from org.orekit.orbits import KeplerianOrbit, PositionAngleType
    from org.orekit.propagation.analytical import KeplerianPropagator
    from org.orekit.attitudes import NadirPointing, TargetPointing
    from org.hipparchus.geometry.euclidean.threed import RotationOrder, RotationConvention
    from orekit_jpype.pyhelpers import datetime_to_absolutedate as date
    inertial = FramesFactory.getEME2000()
    itrf = FramesFactory.getITRF(IERSConventions.IERS_2010, True)
    earth = OneAxisEllipsoid(Constants.WGS84_EARTH_EQUATORIAL_RADIUS,
                            Constants.WGS84_EARTH_FLATTENING, itrf)
    op = satellite['orbital_params']
    orbit = KeplerianOrbit(op['semi_major_axis_km']*1000, op['eccentricity'],
        math.radians(op['inclination_deg']), math.radians(op['argument_of_perigee_deg']),
        math.radians(op['right_ascension_of_ascending_node_deg']), math.radians(op['mean_anomaly_deg']),
        PositionAngleType.MEAN, inertial, date(parse_orbit_epoch(op['epoch'])), Constants.WGS84_EARTH_MU)
    prop = KeplerianPropagator(orbit)
    lat, lon = map(math.radians, (location['latitude'], location['longitude']))
    geo = GeodeticPoint(lat, lon, location.get('altitude_km', 0)*1000)
    target = earth.transform(geo)
    normal = (math.cos(lat)*math.cos(lon), math.cos(lat)*math.sin(lon), math.sin(lat))
    nominal, pointing = NadirPointing(inertial, earth), TargetPointing(inertial, geo, earth)
    limits = satellite['maneuverability_capability']
    sensor = satellite['observation_capability']['sensors'][0]

    def xyz(vector):
        return tuple(float(getattr(vector, 'get'+axis)()) for axis in 'XYZ')

    def sample(moment):
        dt = date(parse_orbit_epoch(moment))
        state = prop.propagateOrbit(dt)
        sat = state.getPVCoordinates(itrf).getPosition()
        difference = xyz(sat.subtract(target))
        sine = sum(a*b for a,b in zip(difference, normal))/math.sqrt(sum(x*x for x in difference))
        elevation = math.degrees(math.asin(max(-1.,min(1.,sine))))
        n = nominal.getAttitude(prop, dt, inertial)
        body = n if limits['maneuverability_type']=='non_agile' else pointing.getAttitude(prop, dt, inertial)
        b, a = body.getRotation().getMatrix(), n.getRotation().getMatrix()
        relative = [[sum(float(b[i][k])*float(a[j][k]) for k in range(3)) for j in range(3)] for i in range(3)]
        # Passive ZYX: R = Rx(-roll) Ry(-pitch) Rz(-yaw).
        yaw = math.degrees(math.atan2(relative[0][1], relative[0][0]))
        pitch = -math.degrees(math.asin(max(-1., min(1., relative[0][2]))))
        roll = math.degrees(math.atan2(relative[1][2], relative[2][2]))
        absolute = [math.degrees(float(x)) for x in body.getRotation().getAngles(
            RotationOrder.ZYX, RotationConvention.FRAME_TRANSFORM)]
        target_i = itrf.getTransformTo(inertial, dt).transformPosition(target)
        los = xyz(target_i.subtract(state.getPVCoordinates(inertial).getPosition()).normalize())
        body_los = [sum(float(b[i][j])*los[j] for j in range(3)) for i in range(3)]
        z = body_los[2]
        tangent = math.tan(math.radians(sensor['field_of_view_deg']/2))
        fov = z>0 and abs(body_los[0])<=z*tangent and abs(body_los[1])<=z*tangent
        rate = math.degrees(float(body.getSpin().getNorm()))
        angles = absolute if legacy_absolute else (yaw,pitch,roll)
        axes = all(abs(x)<=limits['max_'+axis+'_angle_deg'] for x,axis in zip(angles,('yaw','pitch','roll')))
        speed = rate<=limits.get('slew_rate_deg_per_s',float('inf'))
        # Ground targets on/above a convex WGS84 ellipsoid and positive
        # geodetic-normal elevation have no interior Earth segment.
        unoccluded = location.get('altitude_km',0)>=0 and elevation>0
        return dict(visible=elevation>minimum and axes and fov and speed and unoccluded,
            elevation_deg=elevation, yaw_deg=yaw,pitch_deg=pitch,roll_deg=roll,
            absolute_zyx_deg=absolute, body_los=body_los,camera_visible=fov,
            tracking_rate_deg_s=rate, axis_ok=axes, rate_ok=speed,unoccluded=unoccluded,
            relative_matrix=relative)
    sample.prop, sample.earth, sample.inertial, sample.itrf = prop,earth,inertial,itrf
    return sample


def production_params(satellite, location, minimum=5.):
    op, mc = satellite['orbital_params'], satellite['maneuverability_capability']
    return dict(a_m=op['semi_major_axis_km']*1000,e=op['eccentricity'],i_deg=op['inclination_deg'],
        raan_deg=op['right_ascension_of_ascending_node_deg'],argp_deg=op['argument_of_perigee_deg'],
        m_deg=op['mean_anomaly_deg'],epoch_dt=parse_orbit_epoch(op['epoch']),
        target_lat_deg=location['latitude'],target_lon_deg=location['longitude'],
        target_alt_m=location.get('altitude_km',0)*1000,min_elevation_deg=minimum,
        max_yaw_deg=mc['max_yaw_angle_deg'],max_pitch_deg=mc['max_pitch_angle_deg'],max_roll_deg=mc['max_roll_angle_deg'],
        field_of_view_deg=satellite['observation_capability']['sensors'][0]['field_of_view_deg'],
        maneuverability_type=mc['maneuverability_type'],max_tracking_rate_deg_s=mc.get('slew_rate_deg_per_s'))


def exit_bracket(evaluate, lower, upper):
    assert evaluate(lower)['visible'] and not evaluate(upper)['visible']
    while upper-lower>timedelta(microseconds=1):
        middle = lower+(upper-lower)//2
        if evaluate(middle)['visible']: lower=middle
        else: upper=middle
    return lower,upper
