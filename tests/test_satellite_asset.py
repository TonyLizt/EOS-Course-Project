import hashlib
import json
import struct
import unittest
from pathlib import Path


class SatelliteAssetTests(unittest.TestCase):
    def test_landsat_glb_matches_manifest_and_has_no_animation(self):
        manifest = json.loads(Path("assets/satellites/asset-manifest.json").read_text(encoding="utf-8"))["assets"][0]
        data = Path(manifest["local_path"]).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), manifest["sha256"])
        self.assertEqual(len(data), manifest["size_bytes"])
        magic, version, declared_length = struct.unpack_from("<4sII", data, 0)
        self.assertEqual((magic, version, declared_length), (b"glTF", 2, len(data)))
        json_length, json_type = struct.unpack_from("<I4s", data, 12)
        self.assertEqual(json_type, b"JSON")
        document = json.loads(data[20:20 + json_length])
        self.assertEqual(document["asset"]["version"], "2.0")
        self.assertEqual(document.get("animations", []), [])
        self.assertIn("KHR_draco_mesh_compression", document["extensionsRequired"])

    def test_display_mapping_does_not_claim_source_satellite_identity(self):
        manifest = json.loads(Path("assets/satellites/asset-manifest.json").read_text(encoding="utf-8"))["assets"][0]
        self.assertEqual(manifest["role"], "visual_appearance_only")
        self.assertIn("satellite IDs and names remain unchanged", manifest["identity_mapping"])
        self.assertFalse(manifest["asset_specific_license_found"])


if __name__ == "__main__":
    unittest.main()
