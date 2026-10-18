"""Rigid body / fixed camera conventions for the reviewed development model.

Orekit rotations map inertial coordinates to body coordinates. TargetPointing
and NadirPointing align body +Z with the ground line of sight. A renderer using
camera -Z must use a FIXED Rx(pi) camera-to-body mount, never a second gimbal.
"""
import math

ATTITUDE_MODEL_VERSION = "nadir_relative_fixed_camera_v1"
CAMERA_TO_BODY_XYZW = (1.0, 0.0, 0.0, 0.0)


def fixed_camera_in_fov(body_los, full_fov_deg):
    """Square full-angle FOV, fixed body +Z optical axis; boundary inclusive."""
    if (isinstance(full_fov_deg, bool) or not math.isfinite(full_fov_deg)
            or not 0 < full_fov_deg < 180):
        raise ValueError("FOV must be a finite full angle in (0,180)")
    x, y, z = map(float, body_los)
    if not all(math.isfinite(v) for v in (x, y, z)) or z <= 0:
        return False
    half = math.radians(full_fov_deg / 2)
    return abs(math.atan2(x, z)) <= half and abs(math.atan2(y, z)) <= half


def relative_body_rotation(target, nominal):
    """R_N->B = R_I->B R_I->N^T (not the inverse composition)."""
    from org.hipparchus.geometry.euclidean.threed import RotationConvention
    return target.compose(nominal.revert(), RotationConvention.VECTOR_OPERATOR)


def quaternion_distance_deg(first, second):
    """SO(3) shortest rotation; q and -q denote the same attitude."""
    if len(first) != 4 or len(second) != 4:
        raise ValueError("quaternions require xyzw")
    norms = [math.sqrt(sum(float(v) ** 2 for v in q)) for q in (first, second)]
    if not all(math.isfinite(n) and abs(n - 1) <= 1e-6 for n in norms):
        raise ValueError("unit finite quaternion required")
    dot = abs(sum(float(a) * float(b) for a, b in zip(first, second)) / math.prod(norms))
    return math.degrees(2 * math.acos(min(1.0, dot)))
